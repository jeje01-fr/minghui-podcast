import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from email.utils import formatdate
from datetime import datetime, timezone
import re
import time

SEARCH_BASE = "https://fr-search.mtcloud.org/?q=%2A&s=date&c=194"
RSS_FILE = "minghui.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151 Safari/537.36"
    )
}

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"

ET.register_namespace("itunes", ITUNES_NS)

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def get_html(url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


# ------------------------------------------------------------
# Lire les épisodes déjà présents dans le RSS
# ------------------------------------------------------------

def load_rss():
    tree = ET.parse(RSS_FILE)
    root = tree.getroot()
    channel = root.find("channel")

    existing_pages = set()
    existing_guids = set()

    for item in channel.findall("item"):

        link = item.findtext("link")

        if link:
            existing_pages.add(link.strip())

        guid = item.findtext("guid")

        if guid:
            existing_guids.add(guid.strip())

    return tree, root, channel, existing_pages, existing_guids


# ------------------------------------------------------------
# Récupérer les podcasts d'une page de recherche
# ------------------------------------------------------------

def extract_search_results(html, page_url):

    soup = BeautifulSoup(html, "html.parser")

    results = []

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if "/html/articles/" not in href:
            continue

        title = clean(a.get_text(" ", strip=True))

        if "podcast" not in title.lower():
            continue

        article_url = urljoin(page_url, href)

        # Date directement à partir de l'URL de l'article
        match = re.search(
            r"/articles/(\d{4})/(\d{1,2})/(\d{1,2})/",
            article_url
        )

        date = None

        if match:
            date = (
                f"{match.group(1)}-"
                f"{match.group(2).zfill(2)}-"
                f"{match.group(3).zfill(2)}"
            )

        results.append({
            "url": article_url,
            "title": title,
            "date": date
        })

    return results


# ------------------------------------------------------------
# Récupérer le MP3 d'un article
# ------------------------------------------------------------

def extract_episode(article):

    html = get_html(article["url"])
    soup = BeautifulSoup(html, "html.parser")

    mp3 = None

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if ".mp3" in href.lower():

            mp3 = urljoin(
                article["url"],
                href
            )

            break

    if not mp3:
        return None

    title = article["title"]

    if soup.title:

        html_title = clean(
            soup.title.get_text()
        )

        html_title = re.sub(
            r"\s*\|\s*Falun Dafa\s*-\s*Minghui\.org.*$",
            "",
            html_title,
            flags=re.IGNORECASE
        )

        if html_title:
            title = html_title

    description = title

    meta = soup.find(
        "meta",
        attrs={"name": "description"}
    )

    if meta:

        description = clean(
            meta.get("content", "")
        )

    return {
        "title": title,
        "description": description,
        "date": article["date"],
        "page": article["url"],
        "mp3": mp3
    }


# ------------------------------------------------------------
# Ajouter un épisode au RSS
# ------------------------------------------------------------

def add_episode(channel, episode):

    item = ET.Element("item")

    ET.SubElement(
        item,
        "title"
    ).text = episode["title"]

    ET.SubElement(
        item,
        "description"
    ).text = episode["description"]

    ET.SubElement(
        item,
        "link"
    ).text = episode["page"]

    guid = ET.SubElement(
        item,
        "guid",
        {"isPermaLink": "false"}
    )

    guid.text = episode["mp3"]

    if episode["date"]:

        dt = datetime.fromisoformat(
            episode["date"]
        ).replace(
            hour=12,
            tzinfo=timezone.utc
        )

        ET.SubElement(
            item,
            "pubDate"
        ).text = formatdate(
            dt.timestamp(),
            usegmt=True
        )

    ET.SubElement(
        item,
        "enclosure",
        {
            "url": episode["mp3"],
            "type": "audio/mpeg"
        }
    )

    ET.SubElement(
        item,
        f"{{{ITUNES_NS}}}author"
    ).text = "Minghui Français"

    # On place le nouvel épisode au début du RSS
    first_item = channel.find("item")

    if first_item is not None:

        index = list(channel).index(first_item)

        channel.insert(
            index,
            item
        )

    else:

        channel.append(item)


# ------------------------------------------------------------
# Programme principal
# ------------------------------------------------------------

def main():

    print("Mise à jour du RSS Minghui")
    print()

    (
        tree,
        root,
        channel,
        existing_pages,
        existing_guids
    ) = load_rss()

    print(
        f"Episodes déjà présents : "
        f"{len(existing_guids)}"
    )

    candidates = []

    # On surveille les 3 premières pages.
    # 75 résultats : largement suffisant pour une
    # vérification toutes les 6 heures.
    for page in range(1, 4):

        if page == 1:

            url = SEARCH_BASE

        else:

            url = (
                f"{SEARCH_BASE}&p={page}"
            )

        print(
            f"Recherche page {page}..."
        )

        html = get_html(url)

        results = extract_search_results(
            html,
            url
        )

        print(
            f"  {len(results)} podcasts trouvés"
        )

        for result in results:

            if result["url"] not in existing_pages:

                candidates.append(result)

        time.sleep(0.5)

    # Suppression des doublons
    unique = {}

    for candidate in candidates:

        unique[candidate["url"]] = candidate

    candidates = list(
        unique.values()
    )

    print()
    print(
        f"Nouveaux articles à vérifier : "
        f"{len(candidates)}"
    )

    added = 0

    # Les résultats sont déjà du plus récent
    # au plus ancien.
    for candidate in candidates:

        print(
            f"  → {candidate['title']}"
        )

        try:

            episode = extract_episode(
                candidate
            )

            if not episode:

                print(
                    "     Aucun MP3"
                )

                continue

            if episode["mp3"] in existing_guids:

                print(
                    "     Déjà présent"
                )

                continue

            add_episode(
                channel,
                episode
            )

            existing_pages.add(
                episode["page"]
            )

            existing_guids.add(
                episode["mp3"]
            )

            added += 1

            print(
                "     ✓ Ajouté"
            )

        except Exception as e:

            print(
                f"     ERREUR : {e}"
            )

        time.sleep(0.3)

    if added:

        tree.write(
            RSS_FILE,
            encoding="utf-8",
            xml_declaration=True
        )

    print()
    print(
        "================================"
    )

    print(
        f"Nouveaux épisodes ajoutés : {added}"
    )

    print(
        f"Total dans le RSS : "
        f"{len(existing_guids)}"
    )

    print(
        "MP3 téléchargés : 0"
    )

    print(
        "================================"
    )


if __name__ == "__main__":
    main()
