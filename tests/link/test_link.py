from copy import deepcopy

import numpy as np

import theano
from theano.graph import basic, fg
from theano.graph.basic import Apply, Constant, Variable
from theano.graph.op import Op
from theano.graph.type import Type
from theano.link.basic import Container, PerformLinker, WrapLinker
from theano.link.c.basic import OpWiseCLinker
from theano.utils import cmp


def as_variable(x):
    assert isinstance(x, Variable)
    return x


class TDouble(Type):
    def filter(self, data):
        return float(data)


tdouble = TDouble()


def double(name):
    return Variable(tdouble, None, None, name=name)


class MyOp(Op):

    __props__ = ("nin", "name", "impl")

    def __init__(self, nin, name, impl=None):
        self.nin = nin
        self.name = name
        if impl:
            self.impl = impl

    def make_node(self, *inputs):
        assert len(inputs) == self.nin
        inputs = [as_variable(i) for i in inputs]
        for input in inputs:
            if input.type is not tdouble:
                raise Exception("Error 1")
        outputs = [double(self.name + "_R")]
        return Apply(self, inputs, outputs)

    def __str__(self):
        return self.name

    def perform(self, node, inputs, out_):
        (out,) = out_
        out[0] = self.impl(*inputs)


add = MyOp(2, "Add", lambda x, y: x + y)
sub = MyOp(2, "Sub", lambda x, y: x - y)
mul = MyOp(2, "Mul", lambda x, y: x * y)
div = MyOp(2, "Div", lambda x, y: x / y)


def notimpl(self, x):
    raise NotImplementedError()


raise_err = MyOp(1, "RaiseErr", notimpl)


def inputs():
    x = double("x")
    y = double("y")
    z = double("z")
    return x, y, z


def perform_linker(fgraph):
    lnk = PerformLinker().accept(fgraph)
    return lnk


def FunctionGraph(inputs, outputs):
    e = fg.FunctionGraph(inputs, outputs)
    return e


class TestPerformLinker:
    def test_thunk(self):
        x, y, z = inputs()
        e = mul(add(x, y), div(x, y))
        fn, i, o = perform_linker(FunctionGraph([x, y, z], [e])).make_thunk()
        i[0].data = 1
        assert i[0].data == 1
        i[1].data = 2
        assert i[1].data == 2
        fn()
        assert o[0].data == 1.5

    def test_function(self):
        x, y, z = inputs()
        e = mul(add(x, y), div(x, y))
        fn = perform_linker(FunctionGraph([x, y, z], [e])).make_function()
        assert fn(1.0, 2.0, 3.0) == 1.5

    def test_constant(self):
        x, y, z = inputs()
        y = Constant(tdouble, 2.0)
        e = mul(add(x, y), div(x, y))
        fn = perform_linker(FunctionGraph([x], [e])).make_function()
        assert fn(1.0) == 1.5

    def test_input_output_same(self):
        x, y, z = inputs()
        fn = perform_linker(FunctionGraph([x], [x])).make_function()
        assert 1.0 == fn(1.0)

    def test_input_dependency0(self):
        x, y, z = inputs()
        a, d = add(x, y), div(x, y)
        e = mul(a, d)
        fn = perform_linker(FunctionGraph(*basic.clone([x, y, a], [e]))).make_function()
        assert fn(1.0, 2.0, 9.0) == 4.5

    def test_skiphole(self):
        x, y, z = inputs()
        a = add(x, y)
        r = raise_err(a)
        e = add(r, a)
        fn = perform_linker(FunctionGraph(*basic.clone([x, y, r], [e]))).make_function()
        assert fn(1.0, 2.0, 4.5) == 7.5


def wrap_linker(fgraph, linkers, wrapper):
    lnk = WrapLinker(linkers, wrapper).accept(fgraph)
    return lnk


class TestWrapLinker:
    def test_0(self):
        nodes = []

        def wrap(fgraph, i, node, th):
            nodes.append(node.op)

        x, y, z = inputs()
        e = mul(add(x, y), div(x, y))
        fn, i, o = wrap_linker(
            FunctionGraph([x, y, z], [e]), [PerformLinker(allow_gc=False)], wrap
        ).make_thunk()
        i[0].data = 1
        i[1].data = 2
        fn()
        assert nodes == [div, add, mul] or nodes == [add, div, mul]
        assert o[0].data is None

    def test_1(self):
        nodes = []

        def wrap(fgraph, i, node, th):
            nodes.append(node.op)
            th()

        x, y, z = inputs()
        e = mul(add(x, y), div(x, y))
        fn, i, o = wrap_linker(
            FunctionGraph([x, y, z], [e]), [PerformLinker(allow_gc=False)], wrap
        ).make_thunk()
        i[0].data = 1
        i[1].data = 2
        fn()
        assert nodes == [div, add, mul] or nodes == [add, div, mul]
        assert o[0].data == 1.5


def test_sort_schedule_fn():
    import theano
    from theano.graph.sched import make_depends, sort_schedule_fn

    x = theano.tensor.matrix("x")
    y = theano.tensor.dot(x[:5] * 2, x.T + 1).T

    def str_cmp(a, b):
        return cmp(str(a), str(b))  # lexicographical sort

    linker = OpWiseCLinker(schedule=sort_schedule_fn(str_cmp))
    mode = theano.Mode(linker=linker)
    f = theano.function((x,), (y,), mode=mode)

    nodes = f.maker.linker.make_all()[-1]
    depends = make_depends()
    for a, b in zip(nodes[:-1], nodes[1:]):
        if not depends((b, a)):
            assert str(a) < str(b)


def test_container_deepcopy():
    # This is a test to a work around a NumPy bug.

    t = theano.tensor.scalar()
    # It seam that numpy.asarray(0.).astype(floatX) can return a numpy
    # scalar with some NumPy Version. So we call numpy.asarray with
    # the dtype parameter.
    v = np.asarray(0.0, dtype=theano.config.floatX)
    assert isinstance(v, np.ndarray), type(v)
    for readonly in [True, False]:
        c = Container(t, [v], readonly=readonly)
        assert isinstance(c.storage[0], np.ndarray), (c.storage[0], type(c.storage[0]))
        assert c.storage[0].dtype == v.dtype, (c.storage[0].dtype, v.dtype)
        assert c.storage[0].dtype == c.type.dtype, (c.storage[0].dtype, c.type.dtype)
        d = deepcopy(c)
        assert isinstance(d.storage[0], np.ndarray), (d.storage[0], type(d.storage[0]))
        assert d.storage[0].dtype == v.dtype, (d.storage[0].dtype, v.dtype)
        assert d.storage[0].dtype == c.type.dtype, (d.storage[0].dtype, c.type.dtype)
