FROM python:3

MAINTAINER Jelle Besseling <jelle@pingiun.com>

COPY . /app

WORKDIR /app

RUN pip install uwsgi && pip install -r requirements.txt

ENV UWSGI_MOUNTPOINT /

ENV UWSGI_APP textshorten:app

CMD /usr/local/bin/uwsgi --socket 0.0.0.0:9001 --manage-script-name --mount $UWSGI_MOUNTPOINT=$UWSGI_APP
