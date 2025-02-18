import aesara
import aesara.tensor as at
import numpy as np
import pytest

from aesara.compile import SharedVariable
from aesara.graph import graph_inputs

import pymc as pm

from pymc.sampling_jax import (
    get_jaxified_logp,
    replace_shared_variables,
    sample_numpyro_nuts,
)


def test_transform_samples():
    aesara.config.on_opt_error = "raise"
    np.random.seed(13244)

    obs = np.random.normal(10, 2, size=100)
    obs_at = aesara.shared(obs, borrow=True, name="obs")
    with pm.Model() as model:
        a = pm.Uniform("a", -20, 20)
        sigma = pm.HalfNormal("sigma")
        b = pm.Normal("b", a, sigma=sigma, observed=obs_at)

        trace = sample_numpyro_nuts(chains=1, random_seed=1322, keep_untransformed=True)

    log_vals = trace.posterior["sigma_log__"].values

    trans_vals = trace.posterior["sigma"].values
    assert np.allclose(np.exp(log_vals), trans_vals)

    assert 8 < trace.posterior["a"].mean() < 11
    assert 1.5 < trace.posterior["sigma"].mean() < 2.5

    obs_at.set_value(-obs)
    with model:
        trace = sample_numpyro_nuts(chains=2, random_seed=1322, keep_untransformed=False)

    assert -11 < trace.posterior["a"].mean() < -8
    assert 1.5 < trace.posterior["sigma"].mean() < 2.5


def test_replace_shared_variables():
    x = aesara.shared(5, name="shared_x")

    new_x = replace_shared_variables([x])
    shared_variables = [var for var in graph_inputs(new_x) if isinstance(var, SharedVariable)]
    assert not shared_variables

    x.default_update = x + 1
    with pytest.raises(ValueError, match="shared variables with default_update"):
        replace_shared_variables([x])


def test_get_jaxified_logp():
    with pm.Model() as m:
        x = pm.Flat("x")
        y = pm.Flat("y")
        pm.Potential("pot", at.log(at.exp(x) + at.exp(y)))

    jax_fn = get_jaxified_logp(m)
    # This would underflow if not optimized
    assert not np.isinf(jax_fn((np.array(5000.0), np.array(5000.0))))
