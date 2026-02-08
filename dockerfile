# Use the latest official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container to /app
WORKDIR /app

# Add the current directory contents into the container at /app
ADD . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir fastapi uvicorn pymysql sqlalchemy 

# Make port 80 available to the world outside this container
EXPOSE 80 

# Run the command to start uvicorn
# Will be arranged in the compose docker file, so not needed here
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--reload"]