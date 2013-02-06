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

logging.basicConfig(filename='stderr.log', filemode='w', level=logging.DEBUG)
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

    def list(self):
        cursor = self.con.cursor()
        cursor.execute("SELECT id, name, vCode FROM api_keys")
        result = cursor.fetchall()
        cursor.close()
        return result

    def fetch(self, name=None, fuzzy=False):
        if name and fuzzy:
            where = "WHERE name LIKE %%%s%%"
        elif name and not fuzzy:
            where = "WHERE name=%s"
        else:
            where = ""

        sql = "SELECT id, name FROM api_keys" + where
        cursor = self.con.cursor()
        qr = cursor.execute(sql)
        d = qr.fetchall()
        cursor.close()
        return d

    def exists(self, keyId, vCode):
        cursor = self.con.cursor()
        qlen = cursor.execute("""SELECT id FROM api_keys WHERE keyId=%s AND vCode=%s""",
                              (keyId, vCode))
        cursor.close()
        if qlen != 0:
            return True
        else:
            return False

class WalletHandler(object):
    def __init__(self, myConnection, urlArgs, characterId, apiId, rediscp):
        self.mdblogger = logging.getLogger('__main__.MySQLdb')
        self._urlArgs = urlArgs
        # max number of entries returned by the API
        self._rowCount = 2560
        self.cid = characterId
        self.apiId = apiId
        self.con = myConnection
        self.__page = 0        # Used to know if we are on the first xml file
        self.__stop_paging = 0 # Set to 1 once we hit already seen refID
        self.redis = redis.Redis(connection_pool=rediscp)

        # if no refID in redis, initialise
        if not self.redis.exists('knownRefID'):
            print('redis refid empty, inserting shit from database')
            cur = self.con.cursor()
            cur.execute('SELECT refID FROM wallet ORDER BY refID ASC')
            data = cur.fetchall()
            for refID in data:
                self.redis.rpush('knownRefID', refID[0])

    def getUrl(self, rowCount, refID=None):
        url = "https://api.eveonline.com/char/WalletJournal.xml.aspx?{}"
        self._urlArgs.update({'characterId': self.cid, 'rowCount': rowCount})
        if refID:
            import copy
            xurlargs = copy.copy(self._urlArgs)
            xurlargs.update({'fromID': refID})
            return url.format(urlencode(xurlargs, doseq=1))
        return url.format(urlencode(self._urlArgs, doseq=1))

    def insertXmlData(self):
        """
        copy xml data into database
        return the number of inserted row
        """
        items = list()
        refIDs = list()
        for item in self.fetchXMLWalletData():
            item = list(item)
            item.append(self.apiId)
            items.append(item)
            refIDs.append(item[3])
        items.reverse()
        if len(items) == 0:
            return 0

        cur = self.con.cursor()
        rowcount = cur.executemany("""INSERT INTO `wallet` (datetime, amount, balance, refID, cId, apiId)
                    VALUES (%s,%s,%s,%s,%s,%s)""", items)
        #rowcount = cur.rowcount
        cur.close()

        self.mdblogger.debug('{0} rows inserted'.format(rowcount))

        if not self.redis.exists('knownRefID'):
            print('insert refid into redis')
            for refID in refIDs:
                self.redis.rpush('knownRefID', str(refID))
        else:
            t = self.redis.lrange('knownRefID', 0, -1)
            diff = list(set(t) - set(refIDs))
            print('insert diff refid into redis')
            if len(diff) > 0:
                for refID in diff:
                    self.redis.rpush('knownRefID', str(refID))

        return rowcount

    def getLastKnownDBDate(self):
        cur = self.con.cursor()
        cur.execute('SELECT MAX(datetime) AS `date` FROM wallet WHERE apiId=%s',
                    self.apiId)
        date = cur.fetchone()
        cur.close()
        return date[0]

    def getMostRecentRefID(self):
        cur = self.con.cursor()
        cur.execute('SELECT refID FROM wallet WHERE apiId=%s ORDER BY refID DESC LIMIT 1',
                    self.apiId)
        refID = cur.fetchone()
        cur.close()
        return refID[0] if refID != None else None

    def fetchXMLWalletData(self, lastDate=0):
        """
        By default, will fetch transactions older than the last transaction
        recorded in the database.
        lastDate can be set, usually to the last time a fetch was done 
        xml: etree object
        cid: characterID
        lastDate: if set, will return only entries with date greater than
                  lastDate
        yield (date, amount, balance, refID, self.cid)
        """
        logger = logging.getLogger('__main__.WalletHandler.fetchXMLWalletData')

        if self.__stop_paging:
            logger.info('Known refID as been spotted, paging ended.')
            return

        #lastPollDate = self.redis.get('lastPollDate')

        # if now isn't greater than the cached time, there is no need to check
        # for updates
        if self.redis.exists('cachedUntil'):
            cu = datetime.strptime(self.redis.get('cachedUntil'), TIMEFORMAT)
            if cu >= datetime.utcnow():
                logger.info('XML Cached time not expired, halting.')
                logger.debug('{0} >= {1}'.format(cu,datetime.utcnow()))
                return

        if self.__page == 1:
            refID = self.getMostRecentRefID()
            xml = getXML(self.getUrl(self._rowCount, refID))
        else:
            xml = getXML(self.getUrl(self._rowCount))

        cachedUntil = datetime.strptime(xml.find('cachedUntil').text, TIMEFORMAT)
        self.redis.set('cachedUntil', cachedUntil)

        knownRefID = self.redis.lrange('knownRefID',0,-1)

        for transaction in xml.findall('result/rowset/row'):
            refId = transaction.attrib['refID']
            if refId in knownRefID:
                self.__stop_paging = 1
                continue
            date = datetime.strptime(transaction.attrib['date'], TIMEFORMAT)
            amount = float(transaction.attrib['amount'])
            balance = float(transaction.attrib['balance'])
            yield (date, amount, balance, refId, self.cid)

class CharacterHandler(object):
    def __init__(self, myConnection, rediscp, keyId, vCode):
        self.mdblogger = logging.getLogger('__main__.MySQLdb')
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
                logger.error('No character for the selected api key.')
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

    def registerCharacterFromApi(self, characterName, characterId):
        cursor = self.con.cursor()
        sql = """INSERT INTO characters (characterName, characterId, apiId)
                 VALUES (%s, %s, %s)"""
        cursor.execute(sql)
        cursor.close()

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
        del(xmlData)

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
        rows = ch.walletHandler.insertXmlData()
        while (rows == ch.walletHandler._rowCount):
            ch.walletHandler.__page = 1
            rows = ch.walletHandler.insertXmlData()


    except MySQLdb.Error, e:
        mdblogger.critical(e.msg)
        raise e
    except:
        raise
    finally:
        if myCon:
            myCon.close()
    