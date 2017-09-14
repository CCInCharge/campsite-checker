import mechanize
import json
import requests
import re
import dotenv
from datetime import datetime
from datetime import timedelta
from bs4 import BeautifulSoup

# Function that acts as a wrapper:
# - Calls the API - DONE
# - Gets all the URLs - DONE
# - Calls the function that pulls the data from a page given an URL
# - Outputs the data to backend endpoint

# FIXME: Returns day use parking

# Types of dates encountered:
# Sun Oct 01 2017 - For use when POSTing to website for initial date
# Oct 1 2017 - likely format for when scraping data
# datetime.date object - stored in actual campsites attribute

class Campground(object):
    def __init__(self, name, url):
        self.name = name
        self.campsites = {}
        self.url = url
    def add_date(self, campsite, date):
        # Expect date to come in the following format:
        # Year Month Day
        if campsite not in self.campsites:
            self.campsites[campsite] = set()
        self.campsites[campsite].add(date)
    def __stringify_campsites(self):
        # Returns a string representation of the campsite names and availability
        # Helper function for jsonify
        if len(self.campsites) == 0:
            return "[{}]"
        campsites_string = "["
        campsite_numbers = sorted(self.campsites.keys())
        last_campsite_number = campsite_numbers[-1]
        for campsite in campsite_numbers:
            campsites_string += '{"' + str(campsite) + '": ['
            dates = sorted(list(self.campsites[campsite]))
            if len(dates) == 0:
                continue
            last_date = dates[-1]
            for date in dates:
                campsites_string += '"' + date.strftime("%Y-%m-%d") + '"'
                if date != last_date:
                    campsites_string += ', '
            campsites_string += ']}'
            if campsite != last_campsite_number:
                campsites_string += ', '
        campsites_string += ']'
        return campsites_string
    def jsonify(self):
        # Returns JSON representation of this object
        json_string = '{"name": "' + self.name + '", '
        json_string += '"url": "' + self.url + '", '
        json_string += '"campsites": ' + self.__stringify_campsites()
        json_string += '}'
        return json.loads(json_string)

class CampgroundList(list):
    """
    Inherits from list, contains several Campground objects.
    Has a method to return a JSON representation of its Campgrounds.
    """
    def serialize(self):
        if len(self) == 0:
            return {"campgrounds": []}

        result = {"campgrounds": [None] * len(self)}
        for idx,campground in enumerate(self):
            result["campgrounds"][idx] = campground.jsonify()
        return result

def get_availability_from_row(row, campground, first_date, last_date):
    """
    Takes a row from the calendar table and extracts the availability of all
    days for that campsite within the given two weeks.

    :param row: bs4.element.Tag representing a row in the calendar table
    :param campground: Campground object to modify
    :param first_date: datetime.date object for the first date in the calendar
    :param last_date: datetime.date object for the last date in the calendar
    """
    campsite = row.find("div", class_="siteListLabel").get_text()
    days = row.find_all("td", class_="status")
    for idx, day in enumerate(days):
        if "a" in day.attrs["class"]:
            date = first_date + timedelta(days=idx)
            campground.add_date(campsite, date)

def get_availability(campground, url, start_date, end_date):
    """
    Gets availability for all campsites for a given campground. Takes in a
    campground object and populates it with campsite availability.

    :param campground: Campground object which will be populated with availability
    :param url: URL of the campground's calendar page
    :param start_date: datetime.date object of the first date to search
    :param end_date: datetime.date object of the last desired date for reservation checking
    """
    br = mechanize.Browser()

    # TODO: Use a UA alias, if exists in Python mechanize
    br.addheaders = [('User-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36')]
    br.set_handle_robots(False)
    br.open(url)

    # First, submit form with given arrival date
    br.select_form("unifSearchForm")
    # Assume that start_date and end_date are datetime.date objects
    br.form['arrivalDate'] = start_date.strftime("%a %b %d %Y")
    br.form['departureDate'] = end_date.strftime("%a %b %d %Y")
    br.submit()

    # Navigate to calendar. Now, first date in calendar will be start_date
    # FIXME: This is not the URL to the calendar - need to follow the calendar link
    text = br.response().read()
    soup = BeautifulSoup(text, "html.parser")
    calendar_url = soup.find("a", id="campCalendar")["href"]
    br.open("https://www.recreation.gov" + calendar_url)

    last_date_reached = False
    last_campsite_reached = False
    while not last_date_reached:
        last_date_reached = False
        last_campsite_reached = False
        while not last_campsite_reached:
            text = br.response().read()
            soup = BeautifulSoup(text, "html.parser")
            calendar = soup.find("table", id="calendar")
            calendar_header = calendar.find("thead")
            cur_month_year = calendar_header.find("td", class_="weeknav month").get_text()

            # cur_month_year might have two months, like so: Oct-Nov 2017
            # cur_month should be Oct in this case
            cur_month = cur_month_year[0:3]

            # If going across years, need to dock one off the year
            # e.g., Dec-Jan 2018 is Dec 2017 - Jan 2018
            if cur_month_year[0:7] == "Dec-Jan":
                cur_year = str(int(cur_month_year[-4:]) - 1)
            else:
                cur_year = cur_month_year[-4:]

            day1_date = calendar_header.find("div", id="day01date").get_text()
            day1_week = calendar_header.find("div", id="day01week").get_text()

            first_date = datetime.strptime(cur_month + " " + day1_date + " "
                + cur_year, "%b %d %Y").date()
            last_date = first_date + timedelta(days=14)

            # Separators have a separator class
            # Rows which contain data for campsites do not have class attribute
            calendar_body = calendar.find("tbody")
            calendar_body_rows = calendar_body.find_all("tr", class_=None)

            # For each row in current 2 weeks, get availability
            for row in calendar_body_rows:
                get_availability_from_row(row, campground, first_date,
                    last_date)

            # Check to see if this is the last campsite
            next_link = calendar.find("tfoot").find("a",
                id=re.compile("resultNext"))
            if ('class' in next_link.attrs.keys()
                and "disabled" in next_link['class']
                ):
                last_campsite_reached = True
            else:
                # Finds link to next set of campsites, making sure to not select
                # the link for the next 2 weeks
                br.follow_link(text_regex=re.compile("(Next)((?!week).)*$"),
                    nr=1)
        # Check to see if this is the last date
        if end_date <= last_date:
            last_date_reached = True
        else:
            # Instead of following the link directly, get the href of the 2 weeks link and just follow it
            # Then, append &startIdx=0 to the end of the url
            next_week_element = calendar_header.find("a", id="nextWeek")
            next_week_link = "https://www.recreation.gov"
            next_week_link += next_week_element["href"]
            next_week_link += "&startIdx=0"
            br.open(next_week_link)
    return campground

class CantAccessAPI(Exception):
    """Raise if request to Recreation.gov API fails for any reason"""
    pass

def get_campgrounds_from_API(latitude, longitude, radius):
    """
    Calls Recreation.gov API with a location and search radius, and returns URLs and campground names
    Returns a list of dicts, with two key-value pairs: campground name and URL
    Returns an empty list if no campgrounds found

    :param latitude: Latitude of coordinate to center the search around
    :param longitude: Longitude of coordinate to center the search around
    :param radius: Radius to search around
    """
    dotenv.load()
    API_KEY = dotenv.get('API_KEY')

    api_url = "https://ridb.recreation.gov/api/v1/facilities.json?apikey="
    api_url += API_KEY
    api_url += "&activity=9"
    api_url += "&latitude=" + str(latitude)
    api_url += "&longitude=" + str(longitude)
    api_url += "&radius=" + str(radius)
    
    # Gets campgrounds from RIDB API
    res = requests.get(api_url)
    if not res.ok:
        raise CantAccessAPI("Unable to access RIDB API. Check your connection and API key")

    res_list = res.json()["RECDATA"]

    # Constructs list of Campgrounds
    results = CampgroundList([None] * len(res_list))
    base_url = "https://www.recreation.gov/camping/"
    base_url_suffix = "/r/campgroundDetails.do?contractCode=NRSO&parkId="

    for idx,campsite in enumerate(res_list):
        facility_name = campsite['FacilityName'].lower().replace(" ", "-")
        facilityID = str(int(campsite['LegacyFacilityID']))

        campground_url = base_url + facility_name + base_url_suffix + facilityID
        name = " ".join(
            w.capitalize() for w in res_list[idx]['FacilityName'].split())
        
        results[idx] = Campground(name, campground_url)
    return results

def get_all_campsite_availability(campgrounds, start_date, end_date):
    for campground in campgrounds:
        get_availability(campground, campground.url, start_date, end_date)
    return campgrounds.serialize()

# Main function for simple testing
if (__name__ == "__main__"):
    """
    url = "https://www.recreation.gov/camping/Hodgdon_Meadow/r/campsiteCalendar.do?page=calendar&search=site&contractCode=NRSO&parkId=70929"
    myCampground = Campground("Hodgdon Meadow", url)
    myCampground = get_availability(myCampground, url, datetime(2017, 10, 5).date(), datetime(2017, 10, 27).date())
    print myCampground.jsonify()
    """
    a = get_campgrounds_from_API(37.827822, -119.544858, 10)
    print a.serialize()
    print get_all_campsite_availability(a, datetime(2017, 10, 5).date(), datetime(2017, 10, 27).date())