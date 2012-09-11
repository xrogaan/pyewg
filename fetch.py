#!/usr/bin/env python2
# vim:set sw=4 ts=4 expandtab textwidth=80:

import os
import sys
import urllib2
import logging
import MySQLdb
import redis
from datetime import datetime
from urllib import urlencode
from StringIO import StringIO
from datetime import datetime
from lxml import etree
import yaml

# dict over tuple:
# con.cursor(MySQLdb.cursors.DictCursor)

logging.basicConfig(filename='stderr.log', level=logging.DEBUG)
TIMEFORMAT = '%Y-%m-%d %H:%M:%S'

class DontRedirect(urllib2.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib2.HTTPError(req.get_full_url(),
                                code, msg, headers, fp)

def getXML(url):
    logger = logging.getLogger('__main__.getXML')
    dn = DontRedirect()
    opener = urllib2.build_opener(dn)
    opener.addheaders = [('User-agent',
                            "python/v%d.%d.%d urllib2" % (sys.version_info[0],
                                                          sys.version_info[1],
                                                          sys.version_info[2]))]
    try:
        logger.info('Opening stream to '+url+' ...')
        response = opener.open(url)
        code = response.code
        logger.info('Got code %d' % code)
        rawdata = response.read()
    except urllib2.URLError, e:
        code = 500
        data = str(e)
        logger.error(data)
        raise e
    except urllib2.HTTPError, e:
        #code = e.code
        logger.error(e.read())
        raise e
    try:
        xml = etree.parse(StringIO(rawdata))
    except etree.XMLSyntaxError, e:
        logger.error('No xml file supplied.')
        raise e

    return xml

class apiHandler(object):
    def __init__(self, myConnection, urlArgs):
        self.con = myConnection
        cursor = self.con.cursor()
        qlen = cursor.execute("""SELECT id FROM api_keys WHERE keyId=%s AND vCode=%s""",
                              (urlArgs['keyId'],urlArgs['vCode']))
        if qlen == 0:
            self._id = cursor.execute("""INSERT INTO api_keys(keyId, vCode, name)
                                      VALUES (%s, %s, '')""", (urlArgs['keyId'],
                                                               urlArgs['vCode']))
        else:
            self._id = cursor.fetchone()[0]
        cursor.close()

class WalletHandler(object):
    def __init__(self, myConnection, urlArgs, characterId, apiId, rediscp):
        url = "https://api.eveonline.com/char/WalletJournal.xml.aspx?{}"
        urlArgs.update({'characterID': characterId,'rowCount':100})
        self.url = url.format(urlencode(urlArgs, doseq=1))
        self.cid = characterId
        self.apiId = apiId
        self.con = myConnection
        self.redis = redis.Redis(connection_pool=rediscp)

    def insertXmlData(self):
        """
        copy xml data into database
        return the number of inserted row
        """
        items = list()
        for item in self.fetchXMLWalletData():
            item = list(item)
            item.append(self.apiId)
            items.append(item)
        items.reverse()
        cur = self.con.cursor()
        cur.executemany("""INSERT INTO `wallet` (datetime, amount, balance, cId, apiId)
                    VALUES (%s,%s,%s,%s,%s)""", items)
        rowcount = cur.rowcount
        cur.close()
        return rowcount

    def getLastKnownDBDate(self):
        cur = self.con.cursor()
        cur.execute('SELECT MAX(datetime) AS `date` FROM wallet WHERE apiId=%s',
                    self.apiId)
        date = cur.fetchone()
        cur.close()
        return date[0]

    def fetchXMLWalletData(self, lastDate=0):
        """
        By default, will fetch transactions older than the last transaction
        recorded in the database.
        lastDate can be set, usually to the last time a fetch was done 
        xml: etree object
        cid: characterID
        lastDate: if set, will return only entries with date greater than
                  lastDate
        yield (date, amount, balance, self.cid)
        """
        logger = logging.getLogger('__main__.WalletHandler.fetchXMLWalletData')
        lastPollDate = self.redis.get('lastPollDate')
        xml = getXML(self.url)

        cu = datetime.strptime(xml.find('cachedUntil').text, TIMEFORMAT)

        if lastPollDate is not None:
            lastPollDate = datetime.strptime(lastPollDate, TIMEFORMAT)
            if lastPollDate <= cu:
                logger.info('XML Cached time not expired, halting.')
                return

        self.redis.set('lastPollDate', cu)

        if not isinstance(lastDate, datetime):
            if int(lastDate) > 0:
                lastDate = datetime.fromtimestamp(lastDate)
            else:
                lastDate = self.getLastKnownDBDate()

        for transaction in xml.findall('result/rowset/row'):
            date = datetime.strptime(transaction.attrib['date'], TIMEFORMAT)
            if lastDate is not None and date < lastDate:
                continue
            amount = float(transaction.attrib['amount'])
            balance = float(transaction.attrib['balance'])
            yield (date, amount, balance, self.cid)

class CharacterHandler(object):
    def __init__(self, myConnection, rediscp, keyId, vCode):
        urlParameters = {'keyId': keyId, 'vCode': vCode}
        url = 'https://api.eveonline.com/account/Characters.xml.aspx'
        self.url = url + '?' + urlencode({'keyId': keyId,
                                          'vCode': vCode})

        self.redis = rediscp
        self.con = myConnection
        self.apiHandler = apiHandler(self.con, urlParameters)

        self.knownIds = list()
        self.fetchCharacterIds()

        if len(self.knownIds) == 0:
            updated = self.updateDbCharacterInfo()
            self.fetchCharacterIds()
            if len(self.knownIds) is 0:
                logger = logging.getLogger('CharacterHandler')
                logger.error('No character for api key.')
                exit()

        self.walletHandler = WalletHandler(self.con, urlParameters, self.knownIds[0],
                                           self.apiHandler._id, rediscp=rediscp)

    def fetchCharacterIds(self):
        c = self.con.cursor()
        c.execute("""SELECT characterId FROM characters WHERE apiId = %s""",
                  self.apiHandler._id)
        while (1):
            row = c.fetchone()
            if row == None:
                break
            self.knownIds.append(row[0])
        c.close()

    def updateDbCharacterInfo(self, forced=False):
        cursor = self.con.cursor()
        try:
            apiId = self.apiHandler._id

            clist = list()
            for character in self.getXmlCharacterInfo():
                clist.append((character['characterName'],
                              character['characterId'],
                              apiId))
            if forced:
                sql = """SELECT characterName, characterId FROM charaters
                         WHERE apiId=%s""" % apiId
                cursor.execute(sql)

                clist2 = list()
                while (1):
                    row = cursor.fetchone()
                    if row == None:
                        break
                    clist2.append((row[0], row[1], apiId))
                clist = list(set(clist) - set(clist2))

            if not clist:
                return 0

            sql = """INSERT INTO characters (characterName, characterId, apiId)
                     VALUES (%s, %s, %s)"""

            if len(clist)>1:
                cursor.executemany(sql, clist)
            else:
                cursor.execute(sql, clist[0])
        except MySQLdb.Error, e:
            logger = logging.getLogger('__main__.CharacterHandler.updateDbCharacterInfo')
            logger.error("%d: %s", e.args[0], e.args[1])
            raise e
        finally:
            cursor.close()
        return len(clist)


    def getXmlCharacterInfo(self):
        xmlData = getXML(self.url)
        characters = list()
        for item in xmlData.findall('result/rowset/row'):
            yield {'characterName': item.attrib['name'],
                   'characterId': item.attrib['characterID']}

    def listDbCharacters(self):
        cur = self.con.cursor()
        qlen = cur.execute("""SELECT characterId, CharacterName, apiId FROM characters""")
        if qlen == 0:
            print('No character in database.')
        else:
            strout='%s (%s) - %s'
            for char in cur.fetchall():
                print(strout % (char[1], char[0], char[2]))
        cur.close()

    def getDbCharactersInfo(self):
        cur = self.con.cursor()
        qlen = cur.execute("SELECT * FROM characters WHERE apiId=%s",
                            (self.apiHandler._id))
        if qlen == 0:
            print('No character in database.')
            return 0
        characterId, characterName = cur.fetchone()
        cursor.close()

        return characterId, characterName

    def getDbCharacterInfo(self, name=None, cId=None):
        if name is None and cId is None:
            print('Either choose a name or character id.')
            return
        elif name is not None:
            where = ('characterName', name)
        elif cId is not None:
            where = ('characterId', cId)
        cur = self.con.cursor()
        ql = cur.execute("""SELECT characterName, characterId, apiId
                         FROM characters WHERE %s = %s""", where)
        if ql == 0:
            print("Character doesn't exists.")
            cursor.close()
            return
        name, cId, apiId = cur.fetchone()
        cursor.close()
        return name, cId, apiId


if __name__ == '__main__':
    #test purpose
    apiData = yaml.load(file('private', 'r'))

    myCon = None
    mdblogger = logging.getLogger('__main__.MySQLdb')
    #mysql
    try:
        # host, user, password, database
        myCon = MySQLdb.connect('localhost', 'test', 'testpwd', 'eveonline')
        pool = redis.ConnectionPool(connection_class=redis.UnixDomainSocketConnection,
                                    path='/tmp/redis.sock')
        ch = CharacterHandler(myConnection=myCon, rediscp=pool, keyId=apiData['keyId'],
                              vCode=apiData['vCode'])
        print(ch.walletHandler.insertXmlData())

    except MySQLdb.Error, e:
        raise e
    except:
        raise
    finally:
        if myCon:
            myCon.close()
    