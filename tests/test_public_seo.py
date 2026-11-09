"""Guard public discovery pages without exposing the signed-in app to search."""

import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "cloudflare-pages" / "frontend"
SITE = "https://goldchat-app.pages.dev"


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.meta = {}
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            self.meta[attrs.get("name", "")] = attrs.get("content", "")
        if tag == "link":
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def read_html(name):
    content = (FRONTEND / name).read_text(encoding="utf-8")
    parser = HeadParser()
    parser.feed(content)
    return content, parser


class PublicSeoTests(unittest.TestCase):
    def test_auth_app_is_not_indexed(self):
        html, head = read_html("index.html")
        self.assertIn("noindex", head.meta["robots"])
        self.assertIn('href="/about/"', html)
        self.assertIn('href="/static/privacy.html"', html)

    def test_public_pages_have_unique_metadata_and_canonicals(self):
        titles = set()
        for name, canonical in (
            ("about/index.html", f"{SITE}/about/"),
            ("about/features.html", f"{SITE}/about/features.html"),
            ("about/guide.html", f"{SITE}/about/guide.html"),
            ("about/download.html", f"{SITE}/about/download.html"),
            ("about/help.html", f"{SITE}/about/help.html"),
            ("about/advertise.html", f"{SITE}/about/advertise.html"),
            ("privacy.html", f"{SITE}/static/privacy.html"),
        ):
            with self.subTest(name=name):
                _, head = read_html(name)
                self.assertTrue(head.title.strip())
                self.assertNotIn(head.title, titles)
                titles.add(head.title)
                self.assertGreater(len(head.meta.get("description", "")), 50)
                self.assertIn(
                    {"rel": "canonical", "href": canonical}, head.links
                )

    def test_sitemap_contains_only_public_pages(self):
        root = ET.parse(FRONTEND / "sitemap.xml").getroot()
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = [item.text for item in root.findall("sm:url/sm:loc", namespace)]
        self.assertEqual(locations, [
            f"{SITE}/about/",
            f"{SITE}/about/features.html",
            f"{SITE}/about/guide.html",
            f"{SITE}/about/download.html",
            f"{SITE}/about/help.html",
            f"{SITE}/about/advertise.html",
            f"{SITE}/static/privacy.html",
        ])
        robots = (FRONTEND / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {SITE}/sitemap.xml", robots)

    def test_payment_page_is_not_indexed(self):
        _, head = read_html("about/payment.html")
        self.assertIn("noindex", head.meta["robots"])


if __name__ == "__main__":
    unittest.main()
