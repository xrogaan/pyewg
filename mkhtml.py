#!/usr/bin/env python2
# -*- coding: utf-8 -*-

from os import path, mkdir
from shutil import copy
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
import MySQLdb

TIMEFORMAT = '%Y-%m-%d %H:%M:%S'

def strtotimestamp(datestr):
	import time
	d = time.strptime(str(datestr), TIMEFORMAT)
	return str(time.mktime(d))

cId = 91439166

con = MySQLdb.connect('localhost', 'test', 'testpwd', 'eveonline')
cur = con.cursor(MySQLdb.cursors.DictCursor)
cur.execute("""
SELECT datetime, SUM(amount) AS amount, MIN(balance) AS balance
FROM wallet
WHERE
	cId=%s AND
	datetime BETWEEN '2012-09-01' AND '2012-09-30'
GROUP BY datetime
ORDER BY refID
""", cId)

rows = cur.fetchall()

cur.close()

env = Environment(loader=FileSystemLoader(path.abspath('./templates')))
env.filters['strptime'] = strtotimestamp
tpl = env.get_template('index.tpl')

tpl.stream(transactions=rows).dump('./output/index.html')


if not path.exists('./output/jquery.min.js'):
	copy('externals/dist/jquery.min.js', 'output/')
if not path.exists('./output/jquery.jqplot.min.js'):
	copy('externals/dist/jquery.jqplot.min.js', 'output/')

if not path.exists('./output/jquery.jqplot.min.css'):
	copy('externals/dist/jquery.jqplot.min.css', 'output/')