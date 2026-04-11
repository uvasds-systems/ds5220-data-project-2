import requests
import boto3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
from datetime import datetime
from boto3.dynamodb.conditions import Key

# ── CONFIG ────────────────────────────────────────────────────────────────────
S3_BUCKET  = os.environ["S3_BUCKET"]
TABLE_NAME = os.environ.get("DYNAMO_TABLE", "opensky-tracking")
REGION     = os.environ.get("AWS_REGION", "us-east-1")

# Tracking Washington DC weather
LAT = 38.9072
LON = -77.0369

# ── 1. CALL OPEN-METEO API (NO AUTH, NO BLOCKING) ────────────────────────────
def fetch_weather():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":            LAT,
        "longitude":           LON,
        "current":             "temperature_2m,wind_speed_10m,precipitation,cloud_cover",
        "temperature_unit":    "fahrenheit",
        "wind_speed_unit":     "mph",
        "timezone":            "UTC",
    }
    print("Calling Open-Meteo API...")
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

# ── 2. PROCESS THE DATA ───────────────────────────────────────────────────────
def process(data):
    current = data["current"]
    return {
        "temperature":  current["temperature_2m"],
        "wind_speed":   current["wind_speed_10m"],
        "precipitation": current["precipitation"],
        "cloud_cover":  current["cloud_cover"],
    }

# ── 3. SAVE TO DYNAMODB ───────────────────────────────────────────────────────
def save_to_dynamo(metrics):
    db = boto3.resource("dynamodb", region_name=REGION)
    table = db.Table(TABLE_NAME)
    timestamp = datetime.utcnow().isoformat()
    item = {
        "source":        "open-meteo",
        "timestamp":     timestamp,
        "temperature":   str(metrics["temperature"]),
        "wind_speed":    str(metrics["wind_speed"]),
        "precipitation": str(metrics["precipitation"]),
        "cloud_cover":   str(metrics["cloud_cover"]),
    }
    table.put_item(Item=item)
    print(f"Saved: {timestamp} | temp={metrics['temperature']}F | wind={metrics['wind_speed']}mph | precip={metrics['precipitation']}mm | cloud={metrics['cloud_cover']}%")

# ── 4. READ ALL HISTORY FROM DYNAMODB ────────────────────────────────────────
def read_history():
    db = boto3.resource("dynamodb", region_name=REGION)
    table = db.Table(TABLE_NAME)
    response = table.query(
        KeyConditionExpression=Key("source").eq("open-meteo")
    )
    items = response["Items"]
    df = pd.DataFrame(items)
    df["timestamp"]    = pd.to_datetime(df["timestamp"])
    df["temperature"]  = df["temperature"].astype(float)
    df["wind_speed"]   = df["wind_speed"].astype(float)
    df["precipitation"] = df["precipitation"].astype(float)
    df["cloud_cover"]  = df["cloud_cover"].astype(float)
    df = df.sort_values("timestamp")
    return df

# ── 5. GENERATE PLOT ──────────────────────────────────────────────────────────
def make_plot(df):
    fig, axes = plt.subplots(4, 1, figsize=(12, 12), sharex=True)
    fig.suptitle("Washington DC Weather — Hourly Tracker", fontsize=14, fontweight="bold")

    axes[0].plot(df["timestamp"], df["temperature"], color="red", marker="o", markersize=3)
    axes[0].set_ylabel("Temperature (°F)")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(df["timestamp"], df["wind_speed"], color="steelblue", marker="o", markersize=3)
    axes[1].set_ylabel("Wind Speed (mph)")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(df["timestamp"], df["precipitation"], color="darkblue", marker="o", markersize=3)
    axes[2].set_ylabel("Precipitation (mm)")
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(df["timestamp"], df["cloud_cover"], color="gray", marker="o", markersize=3)
    axes[3].set_ylabel("Cloud Cover (%)")
    axes[3].set_xlabel("Time (UTC)")
    axes[3].grid(True, alpha=0.3)

    axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig("/tmp/plot.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("Plot saved.")

# ── 6. SAVE CSV ───────────────────────────────────────────────────────────────
def save_csv(df):
    df.to_csv("/tmp/data.csv", index=False)
    print("CSV saved.")

# ── 7. UPLOAD TO S3 ───────────────────────────────────────────────────────────
def upload_to_s3():
    s3 = boto3.client("s3", region_name=REGION)
    s3.upload_file("/tmp/plot.png", S3_BUCKET, "plot.png",
                   ExtraArgs={"ContentType": "image/png"})
    s3.upload_file("/tmp/data.csv", S3_BUCKET, "data.csv",
                   ExtraArgs={"ContentType": "text/csv"})
    print(f"Uploaded plot.png and data.csv to s3://{S3_BUCKET}/")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Weather Pipeline Run ===")
    data    = fetch_weather()
    metrics = process(data)
    save_to_dynamo(metrics)
    df      = read_history()
    make_plot(df)
    save_csv(df)
    upload_to_s3()
    print("=== Done ===")
