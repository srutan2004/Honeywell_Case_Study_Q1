"""
Eco-Loop Building Agents - PMV/PPD Comfort Calculation

Implements the ISO 7730 Predicted Mean Vote (PMV) and Predicted Percentage
of Dissatisfied (PPD) thermal comfort indices.

PMV ranges from -3 (cold) to +3 (hot), with 0 being thermally neutral.
PPD is the predicted percentage of people who would be dissatisfied.

Usage:
    from src.pmv import calculate_pmv, pmv_category
"""

import math


def calculate_pmv(ta, tr=None, vel=0.1, rh=50.0, met=1.2, clo=0.5):
    """
    Calculate PMV and PPD according to ISO 7730.

    Args:
        ta:  Air temperature (C)
        tr:  Mean radiant temperature (C). If None, defaults to ta.
        vel: Air velocity (m/s). Default 0.1 for typical office.
        rh:  Relative humidity (%). Default 50%.
        met: Metabolic rate (met). Default 1.2 (seated office work).
        clo: Clothing insulation (clo). Default 0.5 (summer office).

    Returns:
        dict with 'pmv', 'ppd', 'category' keys
    """
    if tr is None:
        tr = ta

    # Internal heat production (W/m2)
    M = met * 58.15
    W = 0  # External work (0 for office)
    MW = M - W

    # Clothing insulation (m2K/W)
    icl = 0.155 * clo

    # Clothing surface area factor
    if icl <= 0.078:
        fcl = 1.0 + 1.290 * icl
    else:
        fcl = 1.05 + 0.645 * icl

    # Water vapor pressure (Pa)
    pa = rh * 10.0 * math.exp(16.6536 - 4030.183 / (ta + 235.0))

    # Heat transfer coefficient (iterative)
    taa = ta + 273.0
    tra = tr + 273.0

    # Initial guess for clothing surface temperature
    tcla = taa + (35.5 - ta) / (3.5 * (6.45 * icl + 0.1))
    p1 = icl * fcl
    p2 = p1 * 3.96
    p3 = p1 * 100.0
    p4 = p1 * taa
    p5 = 308.7 - 0.028 * MW + p2 * (tra / 100.0) ** 4

    # Iterate to find tcl
    for _ in range(150):
        xn = tcla / 100.0
        xf = xn ** 4
        hcn = 2.38 * abs(100.0 * xn - taa) ** 0.25
        hcf = 12.1 * math.sqrt(vel)
        hc = max(hcn, hcf)
        xn_new = (p5 + p4 * hc - p2 * xf) / (100.0 + p3 * hc)
        if abs(xn_new - xn) < 0.00015:
            break
        tcla = 100.0 * xn_new

    xn = tcla / 100.0
    xf = xn ** 4
    hcn = 2.38 * abs(100.0 * xn - taa) ** 0.25
    hcf = 12.1 * math.sqrt(vel)
    hc = max(hcn, hcf)
    tcl = 100.0 * xn - 273.0

    # PMV calculation
    pm1 = 3.96 * fcl * (xf - (tra / 100.0) ** 4)
    pm2 = fcl * hc * (tcl - ta)
    pm3 = 0.303 * math.exp(-0.036 * M) + 0.028

    pmv = pm3 * (
        MW
        - 3.05e-3 * (5733.0 - 6.99 * MW - pa)
        - 0.42 * (MW - 58.15)
        - 1.7e-5 * M * (5867.0 - pa)
        - 0.0014 * M * (34.0 - ta)
        - pm1
        - pm2
    )

    # Clamp PMV to [-3, 3]
    pmv = max(-3.0, min(3.0, pmv))

    # PPD calculation
    ppd = 100.0 - 95.0 * math.exp(-0.03353 * pmv ** 4 - 0.2179 * pmv ** 2)
    ppd = max(5.0, min(100.0, ppd))

    return {
        "pmv": round(pmv, 2),
        "ppd": round(ppd, 1),
        "category": pmv_category(pmv),
    }


def pmv_category(pmv):
    """
    Return ASHRAE thermal sensation category.

    Returns:
        str: 'Cold', 'Cool', 'Slightly Cool', 'Neutral',
             'Slightly Warm', 'Warm', 'Hot'
    """
    if pmv <= -2.5:
        return "Cold"
    elif pmv <= -1.5:
        return "Cool"
    elif pmv <= -0.5:
        return "Slightly Cool"
    elif pmv <= 0.5:
        return "Neutral"
    elif pmv <= 1.5:
        return "Slightly Warm"
    elif pmv <= 2.5:
        return "Warm"
    else:
        return "Hot"


def is_pmv_comfortable(pmv, threshold=0.7):
    """Check if PMV is within the comfortable range [-threshold, +threshold]."""
    return abs(pmv) <= threshold
