# GitHub Actions - Sensor Data Automation

Automated sensor data download using GitHub Actions with scheduled triggers.

## Architecture

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────┐
│  GitHub Actions     │      │  Ubuntu Runner      │      │  Azure Blob     │
│  Cron: 7:05 AM MYT  │ ──▶  │  Chrome + Selenium  │ ──▶  │  Storage        │
│  (23:05 UTC)        │      │  Python Scripts     │      │  sensor-data/   │
└─────────────────────┘      └─────────────────────┘      └─────────────────┘
```

## Setup Steps

### Step 1: Push Code to GitHub

```powershell
cd "c:\Users\Ang Wei Ding\Desktop\FYP\dataset2\followtime"

# Initialize git if not already done
git init

# Add all files
git add .
git commit -m "Add automated sensor download with GitHub Actions"

# Create repo on GitHub and push
# Replace YOUR_USERNAME with your GitHub username
git remote add origin https://github.com/YOUR_USERNAME/followtime.git
git branch -M main
git push -u origin main
```

### Step 2: Add Azure Storage Secret

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add:
   - **Name:** `AZURE_STORAGE_CONNECTION_STRING`
   - **Value:** Your Azure storage connection string

To get your connection string:
```powershell
az storage account show-connection-string --name sensordata6459 --resource-group sensor-data-rg --query connectionString -o tsv
```

### Step 3: Enable GitHub Actions

GitHub Actions should be enabled by default. The workflow will:
- **Run automatically** at 7:05 AM Malaysia Time (23:05 UTC) every day
- **Manual trigger** available via "Run workflow" button

### Step 4: Test the Workflow

1. Go to your repo on GitHub
2. Click **Actions** tab
3. Select **Sensor Data Download** workflow
4. Click **Run workflow** → **Run workflow**

## Workflow Schedule

The cron schedule `5 23 * * *` means:
- **Minute:** 5
- **Hour:** 23 (UTC)
- **Day of month:** * (every day)
- **Month:** * (every month)
- **Day of week:** * (every day)

23:05 UTC = **7:05 AM Malaysia Time (UTC+8)**

## What Happens Each Run

1. GitHub spins up an Ubuntu runner
2. Installs Python 3.11 and Chrome
3. Runs `main.py --headless --upload-to-blob`
4. Downloads CSV files from Datacake
5. Merges sensor data
6. Uploads to Azure Blob Storage
7. Saves artifacts as backup

## Blob Storage Structure

```
sensor-data/
├── combined/
│   └── merged_sensor_data.csv          # Latest combined data
├── daily/
│   └── 20260214_070500/                # Timestamp folder
│       ├── merged_sensor_data.csv      # Daily merged data
│       └── raw/
│           ├── temperature.csv
│           ├── turbidity.csv
│           ├── tds.csv
│           └── ph.csv
```

## Monitoring

### View Workflow Runs
Go to **Actions** tab in your GitHub repo to see:
- Run history
- Logs
- Download artifacts

### View Blob Storage
```powershell
az storage blob list --container-name sensor-data --account-name sensordata6459 --output table
```

## Troubleshooting

### Workflow not triggering
- Check the Actions tab is enabled in your repo
- Scheduled workflows only run on the default branch (main)

### Download fails
- Check the workflow logs in Actions tab
- Verify Datacake dashboard URL is accessible

### Blob upload fails
- Verify `AZURE_STORAGE_CONNECTION_STRING` secret is set correctly
- Check storage account is accessible

## Cost

| Service | Cost |
|---------|------|
| GitHub Actions | **Free** (2,000 min/month for free accounts) |
| Azure Blob Storage | ~$0.02/GB/month |
| **Total** | **~$0-1/month** |
