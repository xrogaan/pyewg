#!/usr/bin/env python2
# -*- coding: utf-8 -*-

from os import path, mkdir
from shutil import copy
from datetime import datetime
from calendar import monthrange
from jinja2 import Environment, FileSystemLoader
import MySQLdb

TIMEFORMAT = '%Y-%m-%d %H:%M:%S'

def strtotimestamp(datestr):
	import time
	d = time.strptime(str(datestr), TIMEFORMAT)
	return str(time.mktime(d))

cId = 91439166

env = Environment(loader=FileSystemLoader(path.abspath('./templates')))
env.filters['strptime'] = strtotimestamp
tpl = env.get_template('index.tpl')

con = MySQLdb.connect('localhost', 'test', 'testpwd', 'eveonline')
cur = con.cursor(MySQLdb.cursors.DictCursor)

cur.execute("SELECT datetime FROM wallet ORDER BY datetime ASC LIMIT 1")
firstDate = cur.fetchone()['datetime']
cur.execute("SELECT datetime FROM wallet ORDER BY datetime DESC LIMIT 1")
lastDate = cur.fetchone()['datetime']

# from http://stackoverflow.com/a/4040204
if firstDate.year is lastDate.year:
	dates = [datetime(year=firstDate.year, month=mn, day=1) for mn in range(firstDate.month, lastDate.month+1)]
else:
	start_month = firstDate.month
	end_month = (lastDate.year - firstDate.year)*12 + lastDate.month+1
	dates = [datetime(year=yr, month=mn, day=1) for (yr, mn) in (
			((m -1) / 12 + firstDate.year, (m - 1) % 12 + 1) for m in range(start_month, end_month)
		)]

for date in dates:
	days = monthrange(date.year, date.month)[1]
	date0 = '{0}-{1}'.format(date.year, date.month)
	date1 = date0 + '-01'
	date2 = date0 + '-' + str(days)
	sql = """
SELECT datetime, SUM(amount) AS amount, MIN(balance) AS balance
FROM wallet
WHERE
	cId=%s AND
	datetime BETWEEN '{0}' AND '{1}'
GROUP BY datetime
ORDER BY refID
""".format(date1,date2)
	cur.execute(sql, cId)
	rows = cur.fetchall()
	tpl.stream(transactions=rows, monthName=date.strftime('%B'), minDate=date.strftime('%Y-%m-%d')).dump('./output/date-{0}.html'.format(date0))

cur.close()


if not path.exists('./output/jquery.min.js'):
	copy('externals/dist/jquery.min.js', 'output/')
if not path.exists('./output/jquery.jqplot.min.js'):
	copy('externals/dist/jquery.jqplot.min.js', 'output/')

if not path.exists('./output/jquery.jqplot.min.css'):
	copy('externals/dist/jquery.jqplot.min.css', 'output/')