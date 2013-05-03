import unittest
import os
import sys
sys.path.append("..")
from harvest import Harvest, HarvestError, User, Invoice, Client, Contact, HarvestConnectionError
from datetime import datetime, timedelta
from getpass import getpass
import time

try:
    URL = os.environ["harvest_url"]
except KeyError:
    URL = raw_input("your Harvest URL? ")
try:
    USER = os.environ["harvest_user"]
except KeyError:
    USER = raw_input("your Harvest username? ")
try:
    PWD = os.environ["harvest_pwd"]
except KeyError:
    PWD = getpass("your Harvest password? ")

class TestHarvest(unittest.TestCase):
    
    def setUp(self):
        self.harvest = Harvest(URL, USER, PWD)
        
    def test_00_isinstance(self):
        self.assertIsInstance(self.harvest,Harvest)
        
    def test_01_connect_fail(self):
        bad_harvest = Harvest(URL, "bogus_user","badpassword")
        self.assertRaises(Exception,bad_harvest._request, URL + "/people")
        
    def test_02_get_users(self):
        for user in self.harvest.users():
            self.assertIsInstance(user, User)
                
    def test_03_get_invoices(self):
        for inv in self.harvest.invoices():
            self.assertIsInstance(inv, Invoice)
                
    def test_04_get_clients(self):
        for client in self.harvest.clients():
            self.assertIsInstance(client, Client)

if __name__ == '__main__':
    unittest.main()