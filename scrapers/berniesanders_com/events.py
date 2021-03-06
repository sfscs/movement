import logging

import hashlib
import hmac
import time
import urllib
import json

from pytz import timezone
from datetime import datetime
from dateutil import parser

from BeautifulSoup import BeautifulStoneSoup
from HTMLParser import HTMLParser

from models.event import EventProvider
from scrapers.scraper import Scraper
from models.push import PushProvider

logging.basicConfig(format="%(asctime)s - %(levelname)s : %(message)s",
                    level=logging.INFO)

required_keys = [
    "event_id",
    "event_id_obfuscated", 
    "url",
    "name",
    "date",
    "start_time",
    "timezone",
    "description",
    "latitude",
    "longitude",
    "is_official",
    "attendee_count",
    "capacity",
    "site",
    "lang",
    "event_type_name",
    "venue_address1",
    "venue_address2",
    "venue_address3",
    "venue_name",
    "venue_city",
    "venue_state",
    "venue_zip"
]

class EventScraper(Scraper):
    def __init__(self):
        Scraper.__init__(self)
        c = self.config["bsd"]
        self.html = HTMLParser()
        self.call_path = "/page/api/event/search_events"
        self.params = {
            "api_ver": "2",
            "api_id": c["api_id"],
            "api_ts": str(int(time.time()))
        }
        self.signed_params = self.sign_params(c["api_secret"])
        self.url = "".join([
            c["endpoint"],
            self.call_path,
            "?",
            self.signed_params
        ])
        self.map = {
            "event_id": "original_id",
            "start_dt": "start_time"
        }
        self.event_provider = EventProvider()
        self.push_provider = PushProvider()

    def sign_params(self, api_secret):

        signing_string = "\n".join([
            self.params["api_id"],
            self.params["api_ts"],
            self.call_path,
            urllib.urlencode(self.params, doseq=True)
        ])

        api_mac = hmac.new(
            api_secret.encode(),
            signing_string.encode(),
            hashlib.sha1
        ).hexdigest()
        self.params["api_mac"] = api_mac

        query_string = "&".join(
            [key + "=" + str(self.params[key])
             for key in self.params]
        )
        return query_string

    def translate(self, result):

        # Translate normal key names based on map
        result = dict((self.map.get(k, k), v) for (k, v) in result.items())

        msg = json.dumps(result)
        #logging.info(result)
        result["event_id"] = result["original_id"]
        result["venue_state"] = result["venue_state_cd"]

        # Compile Venue
        address_map = {
            "address1" : "addr1",
            "address2" : "addr2",
            "address3" : "addr3"
        }

        # map any available address fields
        for k,v in address_map.iteritems():
            result["venue_"+k] = ''
            try:
                result["venue_"+k] = result["venue_"+v]
            except KeyError:
                pass

        # set sitename
        result["site"] = "berniesanders.com"
        result["lang"] = "en"
        # convert capacity and attendee_count to int's
        for x in ["capacity", "attendee_count"]:
            if x in result and result[x] is not None:
                result[x] = int(result[x])
            else:
                result[x] = 0

        # Convert str to datetime
        result["start_time"] = parser.parse(result["start_time"])
        result["event_date"] = str(result["start_time"].date())
        result["is_official"] = result["is_official"] == "1"
        result["url"] = "https://go.berniesanders.com/page/event/detail/volunteeractivityormeetings/" + result["event_id_obfuscated"]

        # Strip html tags from description
        if result["description"] is not None:
            soup = BeautifulStoneSoup(result["description"], convertEntities=BeautifulStoneSoup.ALL_ENTITIES)
            result["description"] = "\n\n".join(soup.findAll(text=True))

        # timezone
        if result["start_tz"]:
            tz = timezone(result['start_tz'])
            normal = datetime(2009, 9, 1)
            tz_localize = tz.localize(normal, is_dst=None)
            result["timezone"] = tz_localize.tzname()

        for key in required_keys:
            if key not in result:
                result[key] = ''

        return result

    def go(self):
        r = self.get(
            "".join(self.url),
            result_format="json"
        )
        for result in r:
            record = self.translate(result)

            if self.event_provider.exists_by_event_id(record["event_id"]):
                print "found"
                db_event = self.event_provider.read_by_event_id(record["event_id"])
                record["uuid"] = db_event.uuid
                msg = "Updating record for '{0}'."
                logging.info(msg.format(record["name"].encode("utf8")))
                self.event_provider.update_with_hash(record)
            else:
                print "not found"
                msg = "Inserting record for '{0}'."
                logging.info(msg.format(record["name"].encode("utf8")))
                record["timestamp_creation"] = datetime.now()
                result = self.event_provider.create(record)
                # creating pushes for events disabled for now
                # self.push_provider.create_by_foreign_model(result)
            

    def event_exists(self, event_id):
        self.cur.execute("SELECT * FROM event WHERE event_id = (%s)", (event_id,))
        return self.cur.fetchone() is not None
            

if __name__ == "__main__":
    bernie = EventScraper()
    bernie.go()
