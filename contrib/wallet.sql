CREATE DATABASE IF NOT EXISTS `eveonline` DEFAULT CHARACTER SET = 'utf8';

CREATE TABLE IF NOT EXISTS `api_keys` (
    `id` INT(11) NOT NULL,
    `name` VARCHAR(250) NOT NULL,
    `keyId` INT(11) NOT NULL, 
    `vCode` VARCHAR(64) NOT NULL,
    PRIMARY KEY (`id`),
    CONSTRAINT uc_KeyData UNIQUE(keyId, vCode)
) ENGINE MyISAM;

CREATE TABLE IF NOT EXISTS `wallet` (
    `id` INT(11) NOT NULL AUTO_INCREMENT,
    `apiId` INT(11) NOT NULL,
    `cId` INT(11) NOT NULL,
    `datetime` DATETIME NOT NULL,
    `amount` FLOAT(13,2) NOT NULL,
    `balance` FLOAT(15,2) NOT NULL,
    PRIMARY KEY (id), KEY(apiId, cId)
) ENGINE MyISAM;

CREATE TABLE IF NOT EXISTS `characters` (
    `characterId` INT(11) NOT NULL,
    `characterName` VARCHAR(250) NOT NULL,
    `apiId` INT(11) NOT NULL,
    INDEX(apiId),
    UNIQUE(characterId)
) ENGINE MyISAM;
