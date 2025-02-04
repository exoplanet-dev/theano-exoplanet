import numpy as np
import pytest

import theano.tensor as tt
from tests import unittest_tools as utt
from theano import change_flags, config, function
from theano.compile.mode import Mode
from theano.graph.optdb import Query
from theano.tensor.random.utils import RandomStream, broadcast_params


@pytest.fixture(scope="module", autouse=True)
def set_theano_flags():
    opts = Query(include=[None], exclude=[])
    py_mode = Mode("py", opts)
    with change_flags(mode=py_mode, compute_test_value="warn"):
        yield


def test_broadcast_params():

    ndims_params = [0, 0]

    mean = np.array([0, 1, 2])
    cov = np.array(1e-6)
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], mean)
    assert np.array_equal(res[1], np.broadcast_to(cov, (3,)))

    ndims_params = [1, 2]

    mean = np.r_[1, 2, 3]
    cov = np.stack([np.eye(3) * 1e-5, np.eye(3) * 1e-4])
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], np.broadcast_to(mean, (2, 3)))
    assert np.array_equal(res[1], cov)

    mean = np.stack([np.r_[0, 0, 0], np.r_[1, 1, 1]])
    cov = np.arange(3 * 3).reshape((3, 3))
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], mean)
    assert np.array_equal(res[1], np.broadcast_to(cov, (2, 3, 3)))

    mean = np.stack([np.r_[0, 0, 0], np.r_[1, 1, 1]])
    cov = np.stack(
        [np.arange(3 * 3).reshape((3, 3)), np.arange(3 * 3).reshape((3, 3)) * 10]
    )
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], mean)
    assert np.array_equal(res[1], cov)

    mean = np.array([[1, 2, 3]])
    cov = np.stack([np.eye(3) * 1e-5, np.eye(3) * 1e-4])
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], np.array([[1, 2, 3], [1, 2, 3]]))
    assert np.array_equal(res[1], cov)

    mean = np.array([[0], [10], [100]])
    cov = np.diag(np.array([1e-6]))
    params = [mean, cov]
    res = broadcast_params(params, ndims_params)
    assert np.array_equal(res[0], mean)
    assert np.array_equal(res[1], np.broadcast_to(cov, (3, 1, 1)))

    # Try it in Theano
    with change_flags(compute_test_value="raise"):
        mean = tt.tensor(config.floatX, [False, True])
        mean.tag.test_value = np.array([[0], [10], [100]], dtype=config.floatX)
        cov = tt.matrix()
        cov.tag.test_value = np.diag(np.array([1e-6], dtype=config.floatX))
        params = [mean, cov]
        res = broadcast_params(params, ndims_params)
        assert np.array_equal(res[0].get_test_value(), mean.get_test_value())
        assert np.array_equal(
            res[1].get_test_value(), np.broadcast_to(cov.get_test_value(), (3, 1, 1))
        )


class TestSharedRandomStream:
    def setup_method(self):
        utt.seed_rng()

    def test_tutorial(self):
        srng = RandomStream(seed=234)
        rv_u = srng.uniform(0, 1, size=(2, 2))
        rv_n = srng.normal(0, 1, size=(2, 2))

        f = function([], rv_u)
        # Disabling `default_updates` means that we have to pass
        # `srng.state_updates` to `function` manually, if we want the shared
        # state to change
        g = function([], rv_n, no_default_updates=True)
        nearly_zeros = function([], rv_u + rv_u - 2 * rv_u)

        assert np.all(f() != f())
        assert np.all(g() == g())
        assert np.all(abs(nearly_zeros()) < 1e-5)
        assert isinstance(rv_u.rng.get_value(borrow=True), np.random.RandomState)

    def test_basics(self):
        random = RandomStream(seed=utt.fetch_seed())

        with pytest.raises(TypeError):
            random.uniform(0, 1, size=(2, 2), rng=np.random.RandomState(23))

        with pytest.raises(AttributeError):
            random.blah

        with pytest.raises(AttributeError):
            np_random = RandomStream(namespace=np)
            np_random.ndarray

        fn = function([], random.uniform(0, 1, size=(2, 2)), updates=random.updates())

        fn_val0 = fn()
        fn_val1 = fn()

        rng_seed = np.random.RandomState(utt.fetch_seed()).randint(2 ** 30)
        rng = np.random.RandomState(int(rng_seed))  # int() is for 32bit

        numpy_val0 = rng.uniform(0, 1, size=(2, 2))
        numpy_val1 = rng.uniform(0, 1, size=(2, 2))

        assert np.allclose(fn_val0, numpy_val0)
        assert np.allclose(fn_val1, numpy_val1)

    def test_seed(self):
        init_seed = 234
        random = RandomStream(init_seed)

        ref_state = np.random.RandomState(init_seed).get_state()
        random_state = random.gen_seedgen.get_state()
        assert random.default_instance_seed == init_seed
        assert np.array_equal(random_state[1], ref_state[1])
        assert random_state[0] == ref_state[0]
        assert random_state[2:] == ref_state[2:]

        new_seed = 43298
        random.seed(new_seed)

        ref_state = np.random.RandomState(new_seed).get_state()
        random_state = random.gen_seedgen.get_state()
        assert np.array_equal(random_state[1], ref_state[1])
        assert random_state[0] == ref_state[0]
        assert random_state[2:] == ref_state[2:]

        random.seed()
        ref_state = np.random.RandomState(init_seed).get_state()
        random_state = random.gen_seedgen.get_state()
        assert random.default_instance_seed == init_seed
        assert np.array_equal(random_state[1], ref_state[1])
        assert random_state[0] == ref_state[0]
        assert random_state[2:] == ref_state[2:]

        # Reset the seed
        random.seed(new_seed)

        # Check state updates
        _ = random.normal()

        # Now, change the seed when there are state updates
        random.seed(new_seed)

        rng = np.random.RandomState(new_seed)
        update_seed = rng.randint(2 ** 30)
        ref_state = np.random.RandomState(update_seed).get_state()
        random_state = random.state_updates[0][0].get_value(borrow=True).get_state()
        assert np.array_equal(random_state[1], ref_state[1])
        assert random_state[0] == ref_state[0]
        assert random_state[2:] == ref_state[2:]

    def test_uniform(self):
        # Test that RandomStream.uniform generates the same results as numpy
        # Check over two calls to see if the random state is correctly updated.
        random = RandomStream(utt.fetch_seed())
        fn = function([], random.uniform(-1, 1, size=(2, 2)))
        fn_val0 = fn()
        fn_val1 = fn()

        rng_seed = np.random.RandomState(utt.fetch_seed()).randint(2 ** 30)
        rng = np.random.RandomState(int(rng_seed))  # int() is for 32bit
        numpy_val0 = rng.uniform(-1, 1, size=(2, 2))
        numpy_val1 = rng.uniform(-1, 1, size=(2, 2))

        assert np.allclose(fn_val0, numpy_val0)
        assert np.allclose(fn_val1, numpy_val1)

    def test_default_updates(self):
        # Basic case: default_updates
        random_a = RandomStream(utt.fetch_seed())
        out_a = random_a.uniform(0, 1, size=(2, 2))
        fn_a = function([], out_a)
        fn_a_val0 = fn_a()
        fn_a_val1 = fn_a()
        assert not np.all(fn_a_val0 == fn_a_val1)

        nearly_zeros = function([], out_a + out_a - 2 * out_a)
        assert np.all(abs(nearly_zeros()) < 1e-5)

        # Explicit updates #1
        random_b = RandomStream(utt.fetch_seed())
        out_b = random_b.uniform(0, 1, size=(2, 2))
        fn_b = function([], out_b, updates=random_b.updates())
        fn_b_val0 = fn_b()
        fn_b_val1 = fn_b()
        assert np.all(fn_b_val0 == fn_a_val0)
        assert np.all(fn_b_val1 == fn_a_val1)

        # Explicit updates #2
        random_c = RandomStream(utt.fetch_seed())
        out_c = random_c.uniform(0, 1, size=(2, 2))
        fn_c = function([], out_c, updates=[out_c.update])
        fn_c_val0 = fn_c()
        fn_c_val1 = fn_c()
        assert np.all(fn_c_val0 == fn_a_val0)
        assert np.all(fn_c_val1 == fn_a_val1)

        # No updates at all
        random_d = RandomStream(utt.fetch_seed())
        out_d = random_d.uniform(0, 1, size=(2, 2))
        fn_d = function([], out_d, no_default_updates=True)
        fn_d_val0 = fn_d()
        fn_d_val1 = fn_d()
        assert np.all(fn_d_val0 == fn_a_val0)
        assert np.all(fn_d_val1 == fn_d_val0)

        # No updates for out
        random_e = RandomStream(utt.fetch_seed())
        out_e = random_e.uniform(0, 1, size=(2, 2))
        fn_e = function([], out_e, no_default_updates=[out_e.rng])
        fn_e_val0 = fn_e()
        fn_e_val1 = fn_e()
        assert np.all(fn_e_val0 == fn_a_val0)
        assert np.all(fn_e_val1 == fn_e_val0)

    def test_multiple_rng_aliasing(self):
        # Test that when we have multiple random number generators, we do not alias
        # the state_updates member. `state_updates` can be useful when attempting to
        # copy the (random) state between two similar theano graphs. The test is
        # meant to detect a previous bug where state_updates was initialized as a
        # class-attribute, instead of the __init__ function.

        rng1 = RandomStream(1234)
        rng2 = RandomStream(2392)
        assert rng1.state_updates is not rng2.state_updates
        assert rng1.gen_seedgen is not rng2.gen_seedgen

    def test_random_state_transfer(self):
        # Test that random state can be transferred from one theano graph to another.

        class Graph:
            def __init__(self, seed=123):
                self.rng = RandomStream(seed)
                self.y = self.rng.uniform(0, 1, size=(1,))

        g1 = Graph(seed=123)
        f1 = function([], g1.y)
        g2 = Graph(seed=987)
        f2 = function([], g2.y)

        for (su1, su2) in zip(g1.rng.state_updates, g2.rng.state_updates):
            su2[0].set_value(su1[0].get_value())

        np.testing.assert_array_almost_equal(f1(), f2(), decimal=6)
