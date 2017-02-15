FROM python:3

MAINTAINER Jelle Besseling <jelle@pingiun.com>

COPY . /app

WORKDIR /app

RUN pip install uwsgi && pip install -r requirements.txt

VOLUME ["/app/socket/"]

ENV UWSGI_MOUNTPOINT /

ENV UWSGI_APP urlshorten:app

CMD /usr/local/bin/uwsgi -s /app/socket/uwsgi.sock --manage-script-name --mount $UWSGI_MOUNTPOINT=$UWSGI_APP
