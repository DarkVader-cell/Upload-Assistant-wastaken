# ruff: noqa: S101
import pytest

from src.torrentcreate import mkbrr_worker_args


@pytest.mark.parametrize('value',[None,0,'0','','auto',' AUTO '])
def test_automatic_worker_count_never_passes_none_or_zero(value):
    assert mkbrr_worker_args(value)==[]


@pytest.mark.parametrize('value',[1,'8',16])
def test_explicit_worker_count(value):
    assert mkbrr_worker_args(value)==['--workers',str(value)]


@pytest.mark.parametrize('value',[-1,'-1','bad','1.5',True,10000])
def test_invalid_worker_count_is_rejected(value):
    with pytest.raises(ValueError):
        mkbrr_worker_args(value)
