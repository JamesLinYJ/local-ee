FROM python:3.11-slim-trixie@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce AS builder
ENV DEBIAN_FRONTEND=noninteractive JAVA_HOME=/opt/java PYSPARK_PYTHON=/usr/local/bin/python \
    SPARK_HOME=/usr/local/lib/python3.11/site-packages/pyspark GEOPYSPARK_JARS_PATH=/opt/jars
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    openjdk-21-jdk-headless build-essential pkg-config cmake ninja-build libboost-dev \
    libtiff-dev libgeos-dev libproj-dev libnetcdf-dev libhdf5-dev libudunits2-0 libpng-dev libexpat1-dev \
    && ln -s /usr/lib/jvm/java-21-openjdk-$(dpkg --print-architecture) /opt/java \
    && rm -rf /var/lib/apt/lists/*
COPY vendor/gdal /src/gdal
RUN cmake -S /src/gdal -B /tmp/gdal-build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_PYTHON_BINDINGS=OFF -DBUILD_JAVA_BINDINGS=OFF -DBUILD_TESTING=OFF \
      -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF -DOGR_BUILD_OPTIONAL_DRIVERS=OFF \
      -DGDAL_ENABLE_DRIVER_NETCDF=ON -DGDAL_ENABLE_DRIVER_PNG=ON -DOGR_ENABLE_DRIVER_GEOJSON=ON \
      -DGDAL_USE_CURL=OFF -DGDAL_USE_XML2=OFF -DGDAL_USE_XERCESC=OFF -DGDAL_USE_ODBC=OFF \
      -DGDAL_USE_ARMADILLO=OFF -DGDAL_USE_SQLITE3=OFF \
    && cmake --build /tmp/gdal-build -j6 && cmake --install /tmp/gdal-build && ldconfig
COPY vendor/openeo-python-driver /src/python-driver
COPY vendor/openeo-geopyspark-driver /src/geopyspark-driver
COPY vendor/geopyspark /src/geopyspark
COPY vendor/jep /src/jep
RUN sed -i 's/jep_openeo_numpy==4.1.2/jep==4.1.1/;s/h5py~=3.11.0/h5py==3.15.1/;s/protobuf~=3.9.2/protobuf==5.29.6/;s/elasticsearch==7.16.3/elasticsearch==7.17.13/' /src/geopyspark-driver/setup.py
RUN pip install --no-cache-dir numpy==2.3.3 setuptools==69.5.1 wheel==0.46.3 Cython==3.0.12 pkgconfig==1.5.5 \
    && pip install --no-cache-dir --no-build-isolation /src/jep \
    && pip install --no-cache-dir setuptools==80.9.0 \
    && pip install --no-cache-dir --no-build-isolation /src/geopyspark /src/python-driver /src/geopyspark-driver pyspark==4.0.4 GDAL==3.13.3 urllib3==2.8.0 \
    && pip install --no-cache-dir --no-build-isolation --no-deps --force-reinstall --no-binary=rasterio rasterio==1.3.11 \
    && rm -f /usr/local/lib/python3.11/site-packages/pyspark/jars/spire* \
    && pip install --no-cache-dir setuptools==84.2.1 && pip check
COPY engine/jars /opt/jars
COPY vendor/gdal-warp-bindings /src/gdal-warp-bindings
COPY engine/patch_gdal_jni.py /opt/engine/patch_gdal_jni.py
RUN python /opt/engine/patch_gdal_jni.py \
    && make -C /src/gdal-warp-bindings/src clean \
    && make -C /src/gdal-warp-bindings/src -j4 JAVA_HOME=/opt/java CXXFLAGS='-std=c++17 -include utility' ARCH=$(dpkg --print-architecture) libgdalwarp_bindings-$(dpkg --print-architecture).so \
    && mkdir -p /tmp/jni/resources \
    && cp /src/gdal-warp-bindings/src/libgdalwarp_bindings-$(dpkg --print-architecture).so /tmp/jni/resources/ \
    && jar uf /opt/jars/geotrellis-dependencies-2.6.4_2.13-SNAPSHOT.jar -C /tmp/jni resources
COPY engine/runtime_packages.py /opt/engine/runtime_packages.py
RUN python /opt/engine/runtime_packages.py > /opt/runtime-packages.txt

FROM python:3.11-slim-trixie@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce AS runtime
COPY --from=builder /opt/runtime-packages.txt /opt/runtime-packages.txt
RUN apt-get update && apt-get upgrade -y && xargs apt-get install -y --no-install-recommends < /opt/runtime-packages.txt && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local /usr/local
COPY --from=builder /opt/jars /opt/jars
COPY --from=eclipse-temurin:21-jre-noble /opt/java/openjdk /opt/java21
COPY engine/security-jars /opt/security-jars
COPY engine/security-jar-lock.json /opt/security-jar-lock.json
COPY engine/harden_jars.py /opt/engine/harden_jars.py
RUN python /opt/engine/harden_jars.py && rm -rf /opt/security-jars
COPY engine/run.py engine/config.py /opt/engine/
COPY engine/log4j2.xml /usr/local/lib/python3.11/site-packages/scripts/batch_job_log4j2.xml
RUN ldconfig && ln -s /usr/local/lib/python3.11/site-packages/jep/libjep.so /usr/lib/libjep.so \
    && groupadd -g 1000 engine && useradd -u 1000 -g 1000 -d /tmp engine && mkdir -p /job && chown engine:engine /job \
    && pip freeze > /opt/python-freeze.txt && sha256sum /opt/jars/*.jar > /opt/jars-built.sha256
ENV JAVA_HOME=/opt/java21 PATH=/opt/java21/bin:$PATH PYSPARK_PYTHON=/usr/local/bin/python \
    SPARK_HOME=/usr/local/lib/python3.11/site-packages/pyspark GEOPYSPARK_JARS_PATH=/opt/jars \
    OPENEO_BACKEND_CONFIG=/opt/engine/config.py OPENEO_LOCAL_DEBUGGING=false \
    OPENEO_OTEL_ENABLED=false OTEL_SDK_DISABLED=true OTEL_TRACES_EXPORTER=none \
    OTEL_METRICS_EXPORTER=none OTEL_LOGS_EXPORTER=none GDAL_PAM_ENABLED=NO \
    AWS_EC2_METADATA_DISABLED=true HOME=/tmp PYTHONUNBUFFERED=1 PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
WORKDIR /job
USER 1000:1000
ENTRYPOINT ["python", "/opt/engine/run.py"]
