#!/usr/bin/env bash
mkdir -p dist
rm -rf dist/*
rm aws_cowcatcher.zip

cp *.py dist
cp -R cowdefs dist
pip install -r requirements.txt -t dist

(cd dist && zip -r ../aws_cowcatcher *)
