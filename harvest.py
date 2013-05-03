import base64 
import datetime
import decimal
import functools
import string
import types
from urllib import urlencode
import urllib2
from xml.etree import ElementTree

from dateutil import parser as date_parser

USER_AGENT = 'harvest.py'

class HarvestError(Exception): pass

class HarvestConnectionError(HarvestError): pass

class Harvest(object):
    def __init__(self, url, email, password):
        self.base_url = url
        self.headers = {
            'Authorization': 'Basic %s' % (base64.b64encode(
                '%s:%s' % (email, password))),
            'Accept': 'application/xml',
            'Content-Type': 'application/xml',
            'User-Agent': USER_AGENT,
            }

    ##
    # makes an HTTP request to Harvest, passing the provided arguments.
    # Returns an ElementTree root object containing the xml response
    #
    # @param url the uniform resource locator being requested
    # @keyparam data any post data to include.
    # @keyparam method the REST method to use (GET, HEAD, POST, DELETE)
    # @exception HarvestConnectionError if call to urlopen fails.
    # @exception HarvestError if ElementTree parsing of results fails.
    
    def _request(self, url, data=None, method=None):
        
        request = HTTPRequest(
            url=self.base_url + url,
            headers=self.headers,
            data=data,
            method=method,
            )

        try:
            response = urllib2.urlopen(request)
        except urllib2.URLError, e:
            print e, url
            raise HarvestConnectionError(*e.args)

        try:
            return ElementTree.parse(response)
        except ElementTree.ParseError, e:
            raise HarvestError('Parse Error', *e.args)
    
    ##
    # gets the next element in the collection 
    #
    # @params cls - an ElementTree Element, url - the Harvest API uri
    # @return the next ElementTree Element from the _get_items generator
    # @defreturn None if the generator is exausted
    
    def _get_item(self, cls, url):
        try:
            return self._get_items(cls, url).next()
        except StopIteration:
            return None
    
    ##
    # A generator function that returns the next available child element
    # with a matching element_name.
    #
    # @param cls the parent element
    # @param url of the Harvest API for this element
    
    def _get_items(self, cls, url):
        
        root = self._request(url)
        for element in root.findall('.//%s' % cls.element_name):
            yield self._item_from_element(cls, element)

    ##
    # converts the element's text value into a Python base type of
    # str, int, float, bool, or passes it to an appropriate parser
    #
    # @param cls the class of object to be returned
    # @param element to parse
    # @return a new instance of cls with a dictionary containing properties
    
    def _item_from_element(self, cls, element):

        def to_python(typ_name, val):
            # a closure...not sure why it's used here tho.
            try:
                typ = dict(
                    str=str,
                    integer=int,
                    float=float,
                    decimal=decimal.Decimal,
                    datetime=date_parser.parse,
                    date=lambda v: date_parser.parse(v).date(),
                    boolean=bool,
                    )[typ_name]
                try:
                    return typ(val)
                except ValueError, e:
                    return typ()
            except:
                return val
            
        data = {}
        
        # creates a dictionary of xml-tag:python typed value
        # the ElementTree.Element.getchildren() method is depricated
        #for prop in element.getchildren():
        for prop in element.getiterator():
            data[prop.tag.replace('-', '_')] = to_python(
                prop.attrib.get('type'), prop.text)
        return cls(self, data)

##
# utility function used by many objects to build a url
#
# @param base_url something like https://[company].harvestapp.com
# @param *parts any additional parts of the path needed
# @keyparam **params any query string paramaters to include
# @return urlencoded string representing full url.

def _build_url(base_url, *parts, **params):
    url = '/'.join([base_url] + map(str, parts))
    # sometime *parts contains an extra '/'
    url = url.replace("//","/")
    if params:
        # another closure...
        def to_str(obj):
            if isinstance(obj, datetime.datetime):
                return obj.strftime('%Y-%m-%d %H:%M')
            elif isinstance(obj, datetime.date):
                return obj.strftime('%Y%m%d')
            elif isinstance(obj, bool):
                return obj and 'yes' or 'no'
            else:
                return str(obj)
        params = dict((k, to_str(v)) for k, v in params.items())
        
        url = '%s?%s' % (url, urlencode(params))
        
    return url

        
# Harvest item base classes and magic

class HarvestItemBase(object):
    def __init__(self, harvest, data):
        self.__dict__.update(data)
        self.harvest = harvest

    def __str__(self):
        return '%s: %s' % (self.__class__.__name__,
                           getattr(self, 'name', None) or 
                           getattr(self, 'id', '<no id>'))

##
# converts a CamelCase string to a camel-Case string (with hyphens)
#
# @param name the string to convert
# @return the converted string

def _cls_to_element(name):
    return ''.join(
        [name[0].lower()] 
        + map(lambda l: '-' + l if l in string.uppercase else l, name[1:]))
    
class _GettableType(type):
    def __init__(cls, name, bases, attrs):
        super(_GettableType, cls).__init__(name, bases, attrs)
        
        if not cls.__dict__.get('_abstract'):
        
            # Resolve Item names
            cls.element_name = getattr(cls, 'element_name',
                             _cls_to_element(name))
            cls.plural_name = getattr(cls, 'plural_name',
                             '%ss' % cls.element_name)
            cls.base_url = getattr(cls, 'base_url',
                             '/%s' % cls.plural_name.replace('-', '_'))

            # Auto-add various getters
            def contribute(src, src_name, dest, dest_name):
                if getattr(src, src_name, None):
                    setattr(
                        dest,
                        dest_name.replace('-', '_'),
                        types.MethodType(getattr(src, src_name), None, dest))
            contribute(cls, '_get', Harvest, cls.element_name)
            contribute(cls, '_objects', Harvest, cls.plural_name)
            for parent in getattr(cls, 'parent_items', []):
                contribute(cls, '_sub_get', parent, cls.element_name)
                contribute(cls, '_sub_objects', parent, cls.plural_name)

_item_cache = {}
def _cache_item(f):
    @functools.wraps(f)
    def wrapper(cls, obj, id, no_cache=False):
        cache_key = '%s(%s)' % (cls.__name__, id)
        result = _item_cache.get(cache_key)
        if result is None or no_cache:
            result = f(cls, obj, id)
            _item_cache[cache_key] = result
        return result
    return wrapper

def _cache_items(f):
    @functools.wraps(f)
    def wrapper(cls, obj, **kwargs):
        no_cache = kwargs.pop('no_cache', False)
        
        if kwargs:
            cache_key = None
        elif hasattr(obj, 'id'):
            # cache_key for cls objects that are children of a specific obj
            cache_key = '%s(%s)' % (cls.__name__, obj.id)
        else:
            cache_key = '%s(all)' % cls.__name__
            
        # Check for cached list
        result = _item_cache.get(cache_key, [])
        if result and not no_cache:
            for item in result:
                yield item
            return

        for item in f(cls, obj, **kwargs):
            if hasattr(item, 'id'):
                _item_cache['%s(%s)' % (cls.__name__, item.id)] = item
            if cache_key:
                result.append(item)
            yield item

        # Only cache if all items consumed
        if cache_key:
            _item_cache[cache_key] = result
    return wrapper
                
class HarvestItemGettable(HarvestItemBase):
    __metaclass__ = _GettableType
    _abstract = True

    parent_items = []

    @classmethod
    @_cache_item
    def _sub_get(cls, parent, id):
        url = _build_url(parent.base_url, parent.id, cls.base_url, id)
        return parent.harvest._get_item(cls, url)
        
    @classmethod
    @_cache_items
    def _sub_objects(cls, parent, **params):
        params = dict((k.lstrip('_'), v) for k, v in params.items())
        url = _build_url(parent.base_url, parent.id, cls.base_url, **params)
        return parent.harvest._get_items(cls, url)
    
class HarvestPrimaryGettable(HarvestItemGettable):    
    _abstract = True
    
    get_url = None
    
    @classmethod
    @_cache_item
    def _get(cls, harvest, id):
        url = _build_url(cls.get_url or cls.base_url, id)
        return harvest._get_item(cls, url)
        
    @classmethod
    @_cache_items
    def _objects(cls, harvest, **params):
        url = _build_url(cls.base_url, **params)
        return harvest._get_items(cls, url)
    
    
# Harvest item classes
# http://www.getharvest.com/api

class Entry(HarvestPrimaryGettable):
    element_name = 'day_entry'
    plural_name = 'day_entries'
    base_url = '/daily'
    get_url = '/daily/show'

    def __str__(self):
        return 'task %(hours)0.02f hours for project %(project_id)d' % self.__dict__
    
class Client(HarvestPrimaryGettable):
    def projects(self):
        return Project._objects(self.harvest, client=self.id)

    def invoices(self):
        return Invoice._objects(self.harvest, client=self.id)
    
class Contact(HarvestPrimaryGettable):
    parent_items = [Client]

    def __str__(self):
        return 'Contact: %(first_name)s %(last_name)s' % self.__dict__
    
class Project(HarvestPrimaryGettable):
    def entries(self, start, end, **filters):
        filters.update({'from': start, 'to': end})
        url = _build_url(self.base_url, self.id, 'entries', **filters)
        return self.harvest._get_items(Entry, url)
    
    def expenses(self, start, end, **filters):
        filters.update({'from': start, 'to': end})
        url = _build_url(self.base_url, self.id, 'expenses', **filters)
        return self.harvest._get_items(Expense, url)
    
class Task(HarvestPrimaryGettable):
    pass

class User(HarvestPrimaryGettable):
    base_url = '/people'

    def __str__(self):
        return 'User: %(first_name)s %(last_name)s' % self.__dict__
    
class ExpenseCategory(HarvestPrimaryGettable):
    plural = 'expense-categories'

class Expense(HarvestItemGettable):
    parent_items = [User]
    
class UserAssignment(HarvestItemGettable):
    parent_items = [Project]
    
    def __str__(self):
        return 'user %(user_id)s for project %(project_id)d' % self.__dict__
    
class TaskAssignment(HarvestItemGettable):
    parent_items = [Project]
    
    def __str__(self):
        return 'task %(task_id)s for project %(project_id)d' % self.__dict__
    
class Invoice(HarvestPrimaryGettable):
    pass

class InvoiceMessage(HarvestItemGettable):
    base_url = '/messages'
    parent_items = [Invoice]
    
class Payment(HarvestItemGettable):
    parent_items = [Invoice]
    
class InvoiceItemCategory(HarvestPrimaryGettable):
    plural_name = 'invoice-item-categories'
    
# HTTPRequest to specify HTTP method
    
class HTTPRequest(urllib2.Request):
  def __init__(self, *args, **kwargs):
    self._method = kwargs.pop('method', None)
    urllib2.Request.__init__(self, *args, **kwargs)

  def get_method(self):
    return self._method or urllib2.Request.get_method(self)