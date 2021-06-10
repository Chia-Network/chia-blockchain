FROM ubuntu:20.04

ARG PYTHON_VERSIONS
COPY ./app /app
RUN mkdir /py
RUN mkdir -p /home/chia/.chia && ln -s /app/tests/test-cache/test-plots /home/chia/.chia/test-plots && ln -s /app/tests/test-cache/blocks /home/chia/.chia/blocks
WORKDIR /app
RUN rm -rf ./venv
ENV PYTHON_VERSIONS="$PYTHON_VERSIONS"
RUN echo $PYTHON_VERSIONS | tr ' ' '\n' > /app/pyvers.txt
RUN cat /app/pyvers.txt
RUN apt-get update
RUN apt-get install -y lsb-release python3-venv gcc sudo python3-pytest strace python3-pip wget git
RUN touch /usr/bin/git && chmod +x /usr/bin/git
RUN useradd -u 500 -r -d /home/chia -s /bin/bash -c "chia" chia
RUN echo 'chia ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers
RUN chown -R chia /app /py /home/chia
USER chia
RUN sh create-container.sh
