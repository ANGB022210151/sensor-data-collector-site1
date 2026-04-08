"""
Azure Function Timer Trigger - Runs at 7:05 AM daily
Starts an Azure Container Instance to run the Selenium-based data download.
"""

import azure.functions as func
import logging
import os
from azure.identity import DefaultAzureCredential
from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    ContainerGroup,
    Container,
    ResourceRequests,
    ResourceRequirements,
    OperatingSystemTypes,
    ContainerGroupRestartPolicy,
    EnvironmentVariable,
    ImageRegistryCredential,
)

app = func.FunctionApp()


# Timer trigger: runs at 7:05 AM daily (UTC)
# CRON format: {second} {minute} {hour} {day} {month} {day-of-week}
# Adjust for your timezone - e.g., 7:05 AM Malaysia (UTC+8) = 23:05 UTC previous day
@app.timer_trigger(schedule="0 5 7 * * *", arg_name="mytimer", run_on_startup=False)
def sensor_data_download_timer(mytimer: func.TimerRequest) -> None:
    """
    Timer function that triggers the sensor data download container.
    """
    logging.info("⏰ Timer triggered: Starting sensor data download...")

    try:
        # Get configuration from environment variables
        subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")
        resource_group = os.environ.get("AZURE_RESOURCE_GROUP")
        container_group_name = os.environ.get("CONTAINER_GROUP_NAME", "sensor-download-aci")
        container_image = os.environ.get("CONTAINER_IMAGE")  # e.g., youracr.azurecr.io/sensor-downloader:latest
        
        # Storage connection for the container
        storage_connection = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        blob_container_name = os.environ.get("BLOB_CONTAINER_NAME", "sensor-data")

        if not all([subscription_id, resource_group, container_image]):
            logging.error("Missing required environment variables!")
            logging.error(f"AZURE_SUBSCRIPTION_ID: {'set' if subscription_id else 'MISSING'}")
            logging.error(f"AZURE_RESOURCE_GROUP: {'set' if resource_group else 'MISSING'}")
            logging.error(f"CONTAINER_IMAGE: {'set' if container_image else 'MISSING'}")
            return

        # Authenticate and create ACI client
        credential = DefaultAzureCredential()
        aci_client = ContainerInstanceManagementClient(credential, subscription_id)

        # Define container configuration
        container = Container(
            name="sensor-downloader",
            image=container_image,
            resources=ResourceRequirements(
                requests=ResourceRequests(
                    cpu=1.0,
                    memory_in_gb=2.0
                )
            ),
            environment_variables=[
                EnvironmentVariable(
                    name="AZURE_STORAGE_CONNECTION_STRING",
                    secure_value=storage_connection
                ),
                EnvironmentVariable(
                    name="BLOB_CONTAINER_NAME",
                    value=blob_container_name
                ),
            ]
        )

        # Container registry credentials (if using Azure Container Registry)
        acr_server = os.environ.get("ACR_SERVER")
        acr_username = os.environ.get("ACR_USERNAME")
        acr_password = os.environ.get("ACR_PASSWORD")
        
        image_registry_credentials = None
        if acr_server and acr_username and acr_password:
            image_registry_credentials = [
                ImageRegistryCredential(
                    server=acr_server,
                    username=acr_username,
                    password=acr_password
                )
            ]

        # Define container group
        container_group = ContainerGroup(
            location=os.environ.get("AZURE_LOCATION", "southeastasia"),
            containers=[container],
            os_type=OperatingSystemTypes.LINUX,
            restart_policy=ContainerGroupRestartPolicy.NEVER,
            image_registry_credentials=image_registry_credentials
        )

        # Start the container (async operation)
        logging.info(f"Starting container group: {container_group_name}")
        aci_client.container_groups.begin_create_or_update(
            resource_group,
            container_group_name,
            container_group
        )

        logging.info("✅ Container group started successfully!")
        logging.info(f"Container: {container_image}")
        logging.info(f"Data will be uploaded to blob container: {blob_container_name}")

    except Exception as e:
        logging.error(f"❌ Failed to start container: {str(e)}")
        raise


# Optional: HTTP trigger for manual runs
@app.route(route="trigger-download", auth_level=func.AuthLevel.FUNCTION)
def manual_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP endpoint to manually trigger the download.
    Usage: POST/GET to https://your-function.azurewebsites.net/api/trigger-download?code=<function-key>
    """
    logging.info("Manual trigger received")
    
    # Reuse the timer function logic
    class MockTimer:
        past_due = False
    
    sensor_data_download_timer(MockTimer())
    
    return func.HttpResponse(
        "Download container started successfully!",
        status_code=200
    )
