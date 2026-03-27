FROM python:3.12-slim

RUN pip install --no-cache-dir prometheus-client smbus2

COPY x1201_exporter.py /usr/local/bin/x1201_exporter.py
RUN chmod +x /usr/local/bin/x1201_exporter.py

EXPOSE 9121

# Requires --device /dev/i2c-1 --device /dev/gpiochip0
# or --privileged for I2C and GPIO access
ENTRYPOINT ["python3", "/usr/local/bin/x1201_exporter.py"]
