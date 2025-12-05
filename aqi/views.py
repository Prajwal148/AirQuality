# aqi/views.py
import datetime as dt
from typing import Tuple, Dict, Any
from collections import defaultdict

import requests

from django.shortcuts import render, redirect
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.urls import reverse
from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError
from django.contrib.auth.models import User

from .models import Location, Measurement, Profile, UserVisibility
from .forms import (
    SignUpForm,
    AdminSelectUserForm,
    VisibilityForm,
    BecomeAdminForm,
)
from .decorators import app_admin_required

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"


# -----------------------------------------------------------------------------
# Public pages
# -----------------------------------------------------------------------------
def landing(request):
    """Public landing page with Login/Register/Admin shortcuts."""
    return render(request, "aqi/homepage.html")


def signup(request):
    """
    Public sign-up page: creates a user and logs them in.
    If the user checked 'Request admin privileges', redirect to promo flow.
    """
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            # extra safety: block case-insensitive duplicates up front
            uname = (form.cleaned_data.get("username") or "").strip()
            if User.objects.filter(username__iexact=uname).exists():
                form.add_error("username", "This username is already taken.")
            else:
                try:
                    user = form.save(commit=False)
                    user.username = uname  # ensure trimmed username is saved
                    user.save()
                except IntegrityError:
                    # DB-level unique constraint (race condition or oddity)
                    form.add_error("username", "This username is already taken.")
                else:
                    login(request, user)
                    if form.cleaned_data.get("become_admin"):
                        return redirect("become-admin")
                    return redirect("dashboard")
    else:
        form = SignUpForm()
    return render(request, "registration/signup.html", {
        "form": form,
        "excluded_fields": ["username", "password1", "password2", "become_admin"],
    })

class RoleAwareLoginView(LoginView):
    """
    Sends admins to admin panel; others to dashboard.
    Also prevents non-admins from being redirected via next=/admin-panel/.
    """
    def get_success_url(self):
        user = self.request.user
        next_url = self.get_redirect_url()  # honors ?next= if allowed
        is_admin = bool(getattr(getattr(user, "profile", None), "is_app_admin", False))
        admin_url = reverse("admin-panel")
        dash_url = reverse("dashboard")

        if is_admin:
            return admin_url

        # Non-admin: if next explicitly points to admin panel, ignore it.
        if next_url and next_url.rstrip("/") == admin_url.rstrip("/"):
            return dash_url

        return next_url or dash_url


@login_required
def after_login(request):
    """
    Role-aware redirect after login if you prefer using LOGIN_REDIRECT_URL=/after-login/.
    If you switch to RoleAwareLoginView (recommended), this can remain as a fallback.
    """
    prof = getattr(request.user, "profile", None)
    if prof and prof.is_app_admin:
        return redirect("admin-panel")
    return redirect("dashboard")


# -----------------------------------------------------------------------------
# Geocoding
# -----------------------------------------------------------------------------
def geocode(query: str) -> Tuple[float, float, str]:
    r = requests.get(GEOCODE_URL, params={"name": query, "count": 1}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        raise ValueError("Place not found. Try a different city.")
    res = data["results"][0]

    parts = [res.get("name")]
    if res.get("admin1"):
        parts.append(res["admin1"])
    if res.get("country_code"):
        parts.append(res["country_code"])
    name = ", ".join([p for p in parts if p])

    return float(res["latitude"]), float(res["longitude"]), name


# -----------------------------------------------------------------------------
# AQI helpers
# -----------------------------------------------------------------------------
BREAKPOINTS = {
    "pm2_5": [
        (0.0, 12.0, 0, 50), (12.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200), (150.5, 250.4, 201, 300), (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500)
    ],
    "pm10": [
        (0, 54, 0, 50), (55, 154, 51, 100), (155, 254, 101, 150),
        (255, 354, 151, 200), (355, 424, 201, 300), (425, 504, 301, 400),
        (505, 604, 401, 500)
    ],
    # O3 EPA 8-hr breakpoints in ppm; Open-Meteo ozone is µg/m³ → convert below
    "o3": [
        (0.000, 0.054, 0, 50), (0.055, 0.070, 51, 100), (0.071, 0.085, 101, 150),
        (0.086, 0.105, 151, 200), (0.106, 0.200, 201, 300)
    ],
}

def ugm3_to_ppm_o3(ugm3: float, temp_c: float = 25.0, pressure_hpa: float = 1013.25) -> float:
    """Convert ozone µg/m³ → ppm using molar volume approximation."""
    MW = 48.0
    T = temp_c + 273.15
    Vm = 24.45 * (T / 298.15) * (1013.25 / pressure_hpa)  # L/mol
    return (ugm3 / 1000.0) * (Vm / MW)

def compute_us_aqi(vals: Dict[str, float]) -> int:
    def subindex(p, x):
        for lo, hi, Ilo, Ihi in BREAKPOINTS[p]:
            if lo <= x <= hi:
                return round((Ihi - Ilo) / (hi - lo) * (x - lo) + Ilo)
        return None

    candidates = []
    if (pm := vals.get("pm2_5")) is not None:
        candidates.append(subindex("pm2_5", pm))
    if (pm10 := vals.get("pm10")) is not None:
        candidates.append(subindex("pm10", pm10))
    if (o3ug := vals.get("o3")) is not None:
        o3ppm = ugm3_to_ppm_o3(o3ug)
        o3ppm = max(0.0, min(o3ppm, 0.200))  # clamp to table range
        candidates.append(subindex("o3", o3ppm))
    candidates = [c for c in candidates if c is not None]
    return max(candidates) if candidates else 0

def aqi_category(aqi: int) -> Tuple[str, str]:
    if aqi <= 50: return ("Good", "#009966")
    if aqi <= 100: return ("Moderate", "#FFDE33")
    if aqi <= 150: return ("Unhealthy for Sensitive Groups", "#FF9933")
    if aqi <= 200: return ("Unhealthy", "#CC0033")
    if aqi <= 300: return ("Very Unhealthy", "#660099")
    return ("Hazardous", "#7E0023")

def pollutant_subindices(vals: Dict[str, float]) -> Dict[str, int]:
    out = {}
    if vals.get("pm2_5") is not None:
        out["pm2_5"] = compute_us_aqi({"pm2_5": vals["pm2_5"]})
    if vals.get("pm10") is not None:
        out["pm10"] = compute_us_aqi({"pm10": vals["pm10"]})
    if vals.get("o3") is not None:
        out["o3"] = compute_us_aqi({"o3": vals["o3"]})
    return out


# -----------------------------------------------------------------------------
# Data fetch
# -----------------------------------------------------------------------------
def fetch_air_quality(lat: float, lon: float) -> Dict[str, Any]:
    """Fetch ~7 days of hourly pollutants (UTC, past_days + forecast_days)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pm2_5,pm10,ozone,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide",
        "timezone": "UTC",
        "past_days": 6,
        "forecast_days": 1,
    }
    r = requests.get(AQ_URL, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# -----------------------------------------------------------------------------
# Visibility filtering helpers
# -----------------------------------------------------------------------------
def _filter_by_visibility(user, cur_vals, series, hourly_rows, daily_rows, aqi_now, aqi_cat_color):
    """Apply per-user visibility rules (from UserVisibility)."""
    vis = getattr(user, "visibility", None)
    if not vis:
        return cur_vals, series, hourly_rows, daily_rows, aqi_now, aqi_cat_color

    allowed = set(vis.allowed_keys())

    # AQI tile gate
    if not vis.can_aqi:
        aqi_now = 0
        aqi_cat_color = ("Hidden", "#999999")

    # Filter current tiles
    filtered_current = {}
    for k in ["pm2_5", "pm10", "o3", "co", "no2", "so2"]:
        filtered_current[k] = cur_vals.get(k) if k in allowed else None

    # Filter legacy series
    filtered_series = {"time": series.get("time", [])}
    for k in ["pm2_5", "pm10", "o3", "co", "no2", "so2"]:
        filtered_series[k] = series.get(k, []) if k in allowed else []

    # Filter hourly rows
    filtered_hourly = []
    for row in hourly_rows:
        new = {"time": row["time"], "aqi": row.get("aqi")}
        if "pm2_5" in allowed: new["pm2_5"] = row.get("pm2_5")
        if "pm10"  in allowed: new["pm10"]  = row.get("pm10")
        if "o3"    in allowed: new["o3"]    = row.get("o3")
        filtered_hourly.append(new)

    # Filter daily rows
    filtered_daily = []
    for row in daily_rows:
        new = {"day": row["day"], "aqi": row.get("aqi")}
        if "pm2_5" in allowed: new["pm2_5"] = row.get("pm2_5")
        if "pm10"  in allowed: new["pm10"]  = row.get("pm10")
        if "o3"    in allowed: new["o3"]    = row.get("o3")
        filtered_daily.append(new)

    return filtered_current, filtered_series, filtered_hourly, filtered_daily, aqi_now, aqi_cat_color


# -----------------------------------------------------------------------------
# Become Admin (promo code) + Admin Panel
# -----------------------------------------------------------------------------
@login_required
def become_admin(request):
    """Let a logged-in user become app admin if they know the promo code."""
    if request.method == "POST":
        form = BecomeAdminForm(request.POST)
        if form.is_valid():
            promo = form.cleaned_data["promo_code"]
            if promo and promo == getattr(settings, "APP_ADMIN_PROMO_CODE", ""):
                prof, _ = Profile.objects.get_or_create(user=request.user)
                prof.is_app_admin = True
                prof.save()
                messages.success(request, "You are now an app admin.")
                return redirect("admin-panel")
            messages.error(request, "Invalid promo code.")
    else:
        form = BecomeAdminForm()
    return render(request, "aqi/become_admin.html", {"form": form})


@login_required
@app_admin_required  # <— hard 403 if not admin
def admin_panel(request):
    """Admin page: choose a user and update which parameters they can see."""
    selected_user = None
    vis_form = None

    if request.method == "POST":
        if "select_user" in request.POST:
            select_form = AdminSelectUserForm(request.POST)
            if select_form.is_valid():
                selected_user = select_form.cleaned_data["user"]
        elif "save_visibility" in request.POST:
            select_form = AdminSelectUserForm(request.POST)
            if select_form.is_valid():
                selected_user = select_form.cleaned_data["user"]
            if selected_user:
                vis = getattr(selected_user, "visibility", None)
                if not vis:
                    vis = UserVisibility.objects.create(user=selected_user)
                vis_form = VisibilityForm(request.POST, instance=vis)
                if vis_form.is_valid():
                    vis_form.save()
                    messages.success(request, f"Updated visibility for {selected_user.username}.")
    else:
        select_form = AdminSelectUserForm()

    if selected_user and not vis_form:
        vis = getattr(selected_user, "visibility", None)
        if not vis:
            vis = UserVisibility.objects.create(user=selected_user)
        vis_form = VisibilityForm(instance=vis)

    context = {
        "select_form": select_form,
        "selected_user": selected_user,
        "vis_form": vis_form,
    }
    return render(request, "aqi/admin_panel.html", context)


# -----------------------------------------------------------------------------
# Login-protected dashboard
# -----------------------------------------------------------------------------
@login_required
def home(request):
    context = {"result": None, "error": None}
    q = request.GET.get("q")  # city or ZIP

    if q:
        try:
            lat, lon, placename = geocode(q)
            loc, _ = Location.objects.get_or_create(
                query=q.strip(), lat=lat, lon=lon, defaults={"name": placename}
            )

            data = fetch_air_quality(lat, lon)
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            pm25 = hourly.get("pm2_5", [])
            pm10 = hourly.get("pm10", [])
            o3   = hourly.get("ozone", [])
            co   = hourly.get("carbon_monoxide", [])
            no2  = hourly.get("nitrogen_dioxide", [])
            so2  = hourly.get("sulphur_dioxide", [])

            if not times:
                raise ValueError("No air quality data available at this time.")

            # current = last sample
            cur_vals = {
                "pm2_5": pm25[-1] if pm25 else None,
                "pm10":  pm10[-1] if pm10 else None,
                "o3":    o3[-1]   if o3   else None,
                "co":    co[-1]   if co   else None,
                "no2":   no2[-1]  if no2  else None,
                "so2":   so2[-1]  if so2  else None,
            }
            aqi_now = compute_us_aqi(cur_vals)
            cat, color = aqi_category(aqi_now)

            # persist hourly — API times are UTC (we requested UTC)
            for t, p25, p10v, oz, cco, cno2, cso2 in zip(
                times, pm25 or [None]*len(times), pm10 or [None]*len(times),
                o3 or [None]*len(times), co or [None]*len(times),
                no2 or [None]*len(times), so2 or [None]*len(times)
            ):
                ts = timezone.make_aware(dt.datetime.fromisoformat(t), timezone=dt.timezone.utc)
                Measurement.objects.update_or_create(
                    location=loc, ts=ts,
                    defaults={
                        "pm2_5": p25, "pm10": p10v, "o3": oz, "co": cco, "no2": cno2, "so2": cso2,
                        "aqi_us": compute_us_aqi({"pm2_5": p25, "pm10": p10v, "o3": oz})
                    }
                )

            # Build 7-day hourly rows (for charts)
            hourly_rows = []
            for i, t in enumerate(times):
                vals = {
                    "pm2_5": pm25[i] if pm25 else None,
                    "pm10":  pm10[i] if pm10 else None,
                    "o3":    o3[i]   if o3   else None,
                }
                hourly_rows.append({
                    "time": t,
                    "pm2_5": vals["pm2_5"],
                    "pm10":  vals["pm10"],
                    "o3":    vals["o3"],
                    "aqi":   compute_us_aqi(vals),
                })

            # Daily aggregates (mean for pollutants; AQI = daily max)
            bucket = defaultdict(lambda: {"pm2_5": [], "pm10": [], "o3": [], "aqi": []})
            for row in hourly_rows:
                day = row["time"][:10]  # YYYY-MM-DD
                for k in ["pm2_5", "pm10", "o3"]:
                    if row[k] is not None:
                        bucket[day][k].append(row[k])
                bucket[day]["aqi"].append(row["aqi"])

            def mean_safe(lst):
                lst = [x for x in lst if x is not None]
                return round(sum(lst) / len(lst), 2) if lst else None

            daily_rows = []
            for day, vals in sorted(bucket.items()):
                daily_rows.append({
                    "day": day,
                    "pm2_5": mean_safe(vals["pm2_5"]),
                    "pm10":  mean_safe(vals["pm10"]),
                    "o3":    mean_safe(vals["o3"]),
                    "aqi":   (max(vals["aqi"]) if vals["aqi"] else 0),
                })

            subs = pollutant_subindices(cur_vals)
            dominant = max(subs.items(), key=lambda kv: kv[1])[0] if subs else None

            # Base series payload
            base_series = {
                "time": times,
                "pm2_5": pm25,
                "pm10":  pm10,
                "o3":    o3,
                "co":    co,
                "no2":   no2,
                "so2":   so2,
            }

            # Apply per-user visibility (note: use filtered_current!)
            cur_vals, filt_series, filt_hourly, filt_daily, aqi_now, (cat, color) = _filter_by_visibility(
                request.user, cur_vals, base_series, hourly_rows, daily_rows, aqi_now, (cat, color)
            )

            context["result"] = {
                "place": placename,
                "aqi": aqi_now,
                "category": cat,
                "color": color,
                "dominant": dominant,
                "subindices": subs,
                "current": cur_vals,        # ← filtered current values
                "series": filt_series,
                "hourly": filt_hourly,
                "daily":  filt_daily,
            }

        except Exception as e:
            context["error"] = str(e)

    return render(request, "aqi/index.html", context)
