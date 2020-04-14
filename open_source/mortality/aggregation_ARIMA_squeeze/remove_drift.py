import numpy as np
import statsmodels.api as sm
import xarray as xr


def get_lr_params(ts):
    """
    Fits a linear regression to an input time series and returns the fit params

    Args:
        ts (1-d xarray.DataArray): time series of epsilons
    
    Returns:
        (float): the intercept and slope of the time series
    """
    xdata = np.arange(len(ts))
    xdata = sm.add_constant(xdata)
    model = sm.OLS(ts.values, xdata).fit()
    alpha, beta = model.params
    return alpha, beta


def get_all_lr_params(da):
    """
    Iterates through all time series in an input data array, fits a linear 
    regression to them, and stores the parameters in a dataset. 

    Args:
        da (xarray.DataArray): n-dimensional xarray with "year_id" as a
            dimension
    
    Returns:
        (xarray.Dataset): n-1 dimensional xarray containing the intercept 
            (alpha) and slope (beta) for each combination of coords in da 
            excluding year_id
    """
    # create a dataset to store parameters - fill with nans to start, and get
    # rid of "year_id" dimension
    param_da = da.sel(year_id=da.year_id.values.min()).drop("year_id") * np.nan
    param_ds = xr.Dataset({"alpha": param_da.copy(), 
                           "beta": param_da.copy()})
    
    # fit linear regression by location-age-sex
    for sex_id in da.sex_id.values:
        for age_group_id in da.age_group_id.values:
            for location_id in da.location_id.values:
                sub_dict = {
                    "location_id": location_id,
                    "age_group_id": age_group_id,
                    "sex_id": sex_id
                }
                ts = da.loc[sub_dict]
                alpha, beta = get_lr_params(ts)
                param_ds["alpha"].loc[sub_dict] = alpha
                param_ds["beta"].loc[sub_dict] = beta
    return param_ds


def make_single_predictions(alpha, beta, years, decay):
    """
    Generates predictions of the form y = alpha + beta*time for the years
    in years.past_years (linear regression predictions), then attenuates
    the slope that is added for each year after as

    y_{t+1} = y_t + beta*exp(-decay * time_since_holdout)

    for each year in the future.

    Args:
        alpha (float): intercept for linear regression
        beta (float): slope for linear regression
        years (fbd_core.argparse.YearRange): years to fit and forecast over
        decay (float): rate at which the slope of the line decays once 
            forecasts start

    Returns:
        numpy.array: the predictions generated by the input parameters and years
    """
    linear_years = np.arange(len(years.past_years))
    
    # linear preds first
    preds = alpha + (beta * linear_years)
    # then add the decay year-by-year
    last = preds[-1]
    for year_index in range(len(years.forecast_years)):
        current = last + (beta * np.exp(-decay * year_index))
        preds = np.append(preds, current)
        last = current
    return preds


def get_decayed_drift_preds(eps_da, years, decay):
    """
    Generates attenuated drift predictions for each demographic combo in the 
    input dataset (excluding year_id as a coordinate).

    Args: 
        eps_da (xarray.DataArray): dataarray containing the values to fit and
            remove the drift from
        years (fbd_core.argparse.YearRange): years to fit and forecast over
        decay (float): rate at which the slope of the line decays once
            forecasts start

    Returns:
        xarray.DataArray: predictions (linear regression for past years, 
            attenuated drift for future years) for every demographic combo
            in the input dataarray.
    """
    # find the right linear regression parameters to fit the in-sample data
    params = get_all_lr_params(eps_da)

    # get the right shape for the prediction dataframe - fill with nans
    year_da = xr.DataArray(np.repeat(1, len(years.years)), 
                           coords=[years.years],
                           dims=["year_id"])
    pred_da = params["alpha"] * year_da * np.nan

    # fill up the prediction dataframe by iterating through demographic combos
    for sex_id in pred_da.sex_id.values:
        for age_group_id in pred_da.age_group_id.values:
            for location_id in pred_da.location_id.values:
                sub_dict = {
                    "sex_id": sex_id,
                    "age_group_id": age_group_id,
                    "location_id": location_id
                }
                alpha = params["alpha"].loc[sub_dict].values
                beta = params["beta"].loc[sub_dict].values
                pred_da.loc[sub_dict] = make_single_predictions(alpha, 
                                                                beta, 
                                                                years, 
                                                                decay)
    return pred_da