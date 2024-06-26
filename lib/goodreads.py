from bs4 import BeautifulSoup
import aiohttp

class Book:
    full_title= ""
    title= ""
    series=""
    series_link=""
    authors= []
    rating= ""
    description= ""
    image_link = ""

class Author:
    name=""
    link=""



async def getBook(book_url):
    url_to_scrape = book_url
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url_to_scrape) as response:

            """ try: 
                request_page = urlopen(url_to_scrape)
            except urllib.error.HTTPError as e:
                fut.set_result(None)
                return; """
            
            if(response.status != 200):
                return;
            
            page_html = await response.text()

            html_soup = BeautifulSoup(page_html, 'html.parser')

            book = Book()

            # get book title
            book.full_title = html_soup.find("title").get_text()
            
            title_node = html_soup.find("div", attrs={"class": "BookPageTitleSection__title"})
            
            book.title = title_node.find("h1").get_text()
            
            # not all books have series
            book.series =  title_node.find("h3").get_text() if title_node.find("h3") else ""
            book.series_link = title_node.find("h3").find("a")["href"] if title_node.find("h3") else ""

            # get book authors
            book_authors_list = html_soup.find("div", attrs={"class": "ContributorLinksList"})

            del book.authors[:]
            for contributor in book_authors_list.find_all('a'):
                author = Author()
                author.name = contributor.find("span", attrs={"class": "ContributorLink__name"}).get_text()
                author.link = contributor["href"]
                book.authors.append(author)
            # do interaction here for many authors

            # get book image
            book.image_link = html_soup.find("meta", attrs={"property": "og:image"})["content"]
            # get book description
            book.description = "{}...".format(html_soup.find("div", attrs={"class": "BookPageMetadataSection__description"}).find("span").get_text()[:400])
            # get book rating
            book.rating = html_soup.find("div", attrs={"class": "RatingStatistics__rating"}).get_text()
            return book
