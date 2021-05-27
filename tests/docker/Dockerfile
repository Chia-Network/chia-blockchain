FROM continuumio/miniconda3

# Assume code is mirrored in /app
# Note this is run from ./tests/docker-stage with code mirrored (for install purposes) in
# ./tests/docker-stage/app

ARG PYTHON_VERSIONS
COPY ./app /app
RUN mkdir /root/.chia && ln -s /app/tests/test-cache/test-plots /root/.chia/test-plots && ln -s /app/tests/test-cache/blocks /root/.chia/blocks
WORKDIR /app
ENV PYTHON_VERSIONS="$PYTHON_VERSIONS"
RUN echo $PYTHON_VERSIONS | tr ' ' '\n' > /app/pyvers.txt
RUN cat /app/pyvers.txt
ENV CHIATEST=chiatest
RUN apt-get update
RUN apt-get install -y git lsb-release python3-venv gcc sudo python3-pytest strace
RUN conda init
RUN conda install anaconda-client -n base
RUN sh create-container.sh
