from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


# -----------------------------------------------------------------------------
# Core AQI Models
# -----------------------------------------------------------------------------
class Location(models.Model):
    query = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    lat = models.FloatField()
    lon = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.lat}, {self.lon})"


class Measurement(models.Model):
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="measurements")
    ts = models.DateTimeField()
    aqi_us = models.IntegerField()
    pm10 = models.FloatField(null=True)
    pm2_5 = models.FloatField(null=True)
    o3 = models.FloatField(null=True)
    no2 = models.FloatField(null=True)
    so2 = models.FloatField(null=True)
    co = models.FloatField(null=True)

    class Meta:
        indexes = [models.Index(fields=["location", "ts"])]
        unique_together = ("location", "ts")

    def __str__(self):
        return f"{self.location.name} @ {self.ts}"


# -----------------------------------------------------------------------------
# User Roles and Visibility
# -----------------------------------------------------------------------------
class Profile(models.Model):
    """Extended info for each user (admin role tracking)."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    is_app_admin = models.BooleanField(default=False)

    def __str__(self):
        return f"Profile({self.user.username})"


class UserVisibility(models.Model):
    """Tracks which pollutants each user can view in the dashboard."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="visibility")

    can_pm2_5 = models.BooleanField(default=True)
    can_pm10  = models.BooleanField(default=True)
    can_o3    = models.BooleanField(default=True)
    can_co    = models.BooleanField(default=True)
    can_no2   = models.BooleanField(default=True)
    can_so2   = models.BooleanField(default=True)
    can_aqi   = models.BooleanField(default=True)  # Whether the AQI tile is visible

    def allowed_keys(self):
        """Return the list of pollutant keys this user is allowed to see."""
        keys = []
        if self.can_pm2_5: keys.append("pm2_5")
        if self.can_pm10:  keys.append("pm10")
        if self.can_o3:    keys.append("o3")
        if self.can_co:    keys.append("co")
        if self.can_no2:   keys.append("no2")
        if self.can_so2:   keys.append("so2")
        return keys

    def __str__(self):
        return f"Visibility({self.user.username})"


# -----------------------------------------------------------------------------
# Signals to auto-create profile and visibility when user is created
# -----------------------------------------------------------------------------
@receiver(post_save, sender=User)
def ensure_profile_and_visibility(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
        UserVisibility.objects.create(user=instance)
