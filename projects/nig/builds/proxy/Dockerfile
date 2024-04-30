FROM rapydo/proxy:2.4

WORKDIR /etc/apk/keys/
# install rsyslog
RUN wget http://alpine.adiscon.com/rsyslog@lists.adiscon.com-5a55e598.rsa.pub && \
    echo 'http://alpine.adiscon.com/3.7/stable' >> /etc/apk/repositories && \
    apk update && apk add rsyslog

RUN mkdir -p /etc/rsyslog.d
# download the custom configurations for rsyslog
RUN curl -o /etc/rsyslog.d/01_cineca-nginx.conf https://gitlab.cineca.it/aneri/qradar-tool/-/raw/master/rsyslog-base-conf/rsyslog8.24/01_cineca-nginx.conf && \
    curl -o /etc/rsyslog.d/00_moduleload.conf https://gitlab.cineca.it/aneri/qradar-tool/-/raw/master/rsyslog-base-conf/rsyslog8.24/00_moduleload.conf

# change the hostname
RUN sed -i 's/%HOSTNAME%/'"nig_proxy"'/g' /etc/rsyslog.d/01_cineca-nginx.conf

#for debug change the qradar address
#RUN sed -i 's#qradar-collector.private.cineca.it#qradar-collector.test.it#g' /etc/rsyslog.d/01_cineca-nginx.conf

# comment out the use of imklog module \
RUN sed -i '/^module(load="imklog")/ s/^/#/' /etc/rsyslog.conf

# copy the nginx configuration for qradar
COPY nginx_qradar.conf /etc/nginx/nginx.conf

# add the rsyslog starting to the docker entrypoint
RUN sed -i "$(($(wc -l < /usr/local/bin/docker-entrypoint) - 4))i rsyslogd"  /usr/local/bin/docker-entrypoint
RUN sed -i "$(($(wc -l < /usr/local/bin/docker-entrypoint) - 4))i echo 'rsyslog started'" /usr/local/bin/docker-entrypoint


