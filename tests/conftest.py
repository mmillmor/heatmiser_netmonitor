"""Fixtures: a simulated NetMonitor serving pages shaped like the real ones."""
import pytest
import requests_mock as rm

HOST = "netmonitor.test"
NAMES = ["Study", "Hall", "Playroom", "Kitchen", "Living Room", "Bedroom", "Bathroom",
         "Dan's Room", "Will's Room", "Family Bathroom", "Guest Bedroom", "", "Bedroom 5"]
STATMAP = "1111111111101" + "0" * 19
# Six characters per position: current, target, heating, hot water ("3" = none).
QUICK = ["192110", "181403", "161603", "201903", "141403", "191403", "211413",
         "171803", "202113", "191603", "181403", "000000", "171603"]


def page(**fields):
    return "<html>" + "".join(
        f'<input type=hidden name="{k}" value="{v}">' for k, v in fields.items()
    ) + "</html>"


class FakeNetMonitor:
    def __init__(self):
        self.frost_state = "011001" + "0" * 26  # Hall, Playroom, Bedroom
        self.posts = []

    def quickview(self, request, context):
        return page(hmcookies="11110000", quickview="".join(QUICK),
                    statname="#".join(NAMES), statmap=STATMAP)

    def frost(self, request, context):
        if request.method == "POST":
            self.posts.append(("frost.htm", request.text))
            from urllib.parse import parse_qs
            self.frost_state = parse_qs(request.text)["frostMap"][0]
        return page(frostState=self.frost_state, frostMap="0" * 32)

    def statistics(self, request, context):
        sent = "".join(f"{1000 + i * 100:04d}" for i in range(12))
        recv = "".join(f"{950 + i * 100:04d}" for i in range(12))
        return page(websendCnt=sent, webrecvCnt=recv, prtmap="31111111111!1" + "!" * 19)

    def other_post(self, request, context):
        self.posts.append((request.path, request.text))
        return page(statInfo="21180000000000", hwBoost="ff")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def netmonitor():
    fake = FakeNetMonitor()
    with rm.Mocker() as m:
        base = f"http://{HOST}/"
        m.get(base + "quickview.htm", text=fake.quickview)
        m.get(base + "frost.htm", text=fake.frost)
        m.post(base + "frost.htm", text=fake.frost)
        m.get(base + "statistics.htm", text=fake.statistics)
        m.post(base + "right.htm", text=fake.other_post)
        m.post(base + "tempset.htm", text=fake.other_post)
        yield fake
