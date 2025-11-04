from django.db import models

class Location(models.Model):
    query = models.CharField(max_length=120)
    name = models.CharField(max_length=200)
    lat = models.FloatField()
    lon = models.FloatField()

    def __str__(self): return f"{self.name} ({self.lat}, {self.lon})"

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
