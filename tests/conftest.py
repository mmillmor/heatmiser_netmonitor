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
    """Behaves like the real NetMonitor seen in testing: a change only sticks
    when the same value is sent a second time, and frostState and quickview
    only show changes the stats have applied."""

    def __init__(self):
        self.frost_state = "011001" + "0" * 26  # Hall, Playroom, Bedroom
        self.targets = {i: int(q[2:4]) for i, q in enumerate(QUICK)}
        self.posts = []
        self._seen = {}  # (kind, index, value) -> times sent

    def _apply_if_repeated(self, kind, index, value):
        key = (kind, index, value)
        self._seen[key] = self._seen.get(key, 0) + 1
        return self._seen[key] >= 2

    def quickview(self, request, context):
        quick = [q[:2] + f"{self.targets[i]:02d}" + q[4:] for i, q in enumerate(QUICK)]
        return page(hmcookies="11110000", quickview="".join(quick),
                    statname="#".join(NAMES), statmap=STATMAP)

    def frost(self, request, context):
        if request.method == "POST":
            from urllib.parse import parse_qs
            self.posts.append(("frost.htm", request.text))
            wanted = parse_qs(request.text)["frostMap"][0]
            state = list(self.frost_state)
            for i, (have, want) in enumerate(zip(self.frost_state, wanted)):
                if have != want and self._apply_if_repeated("frost", i, want):
                    state[i] = want
            self.frost_state = "".join(state)
        return page(frostState=self.frost_state, frostMap="0" * 32)

    def tempset(self, request, context):
        from urllib.parse import parse_qs
        self.posts.append(("tempset.htm", request.text))
        q = parse_qs(request.text)
        index = q["quickSetMap"][0].index("1")
        value = int(q["quickSet"][0])
        if self._apply_if_repeated("temp", index, value):
            self.targets[index] = value
        return page()

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
        m.post(base + "tempset.htm", text=fake.tempset)
        yield fake
