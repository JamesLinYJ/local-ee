import numpy as np
import pandas as pd
import xarray as xr
from gee.climate import daily_values

def fixture():
    times=pd.date_range('2024-01-01',periods=73,freq='h')
    temp=np.full((73,2,2),293.15)
    # Hour 00 holds preceding day's 24 h total; hours 01..23 cumulative since today's 00.
    rain=np.array([((t.hour or 24)*.001) for t in times])[:,None,None]*np.ones((1,2,2))
    return xr.Dataset({'t2m':(('time','latitude','longitude'),temp,{'units':'K'}),
                       'tp':(('time','latitude','longitude'),rain,{'units':'m'})},
                       coords={'time':times,'latitude':[22.4,22.3],'longitude':[113.5,113.6]})

def test_era5_accumulation_not_double_counted():
    daily=daily_values(fixture())
    np.testing.assert_allclose(daily.precipitation.sel(time='2024-01-01'),24.)
    np.testing.assert_allclose(daily.temperature.sel(time='2024-01-01'),20.,atol=1e-10)
    assert np.isnan(daily.temperature.sel(time='2024-01-04')).all()

def test_missing_temperature_hour_is_nodata():
    ds=fixture().drop_sel(time=pd.Timestamp('2024-01-01 15:00'))
    assert np.isnan(daily_values(ds).temperature.sel(time='2024-01-01')).all()

def test_missing_rain_boundary_is_not_zero():
    ds=fixture().drop_sel(time=pd.Timestamp('2024-01-02 00:00'))
    assert np.isnan(daily_values(ds).precipitation.sel(time='2024-01-01')).all()

def test_wrong_units_rejected():
    import pytest
    ds=fixture();ds.tp.attrs['units']='mm'
    with pytest.raises(ValueError,match='单位'):daily_values(ds)
