"""HTML content extraction only for explicitly supplied page text, not crawling."""
from html.parser import HTMLParser
class Extractor(HTMLParser):
    def __init__(self):super().__init__();self.text=[];self.ignored=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):self.ignored+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.ignored:self.ignored-=1
    def handle_data(self,data):
        if not self.ignored and data.strip():self.text.append(data.strip())
def extract(html:str)->str:
    p=Extractor();p.feed(html);return '\n'.join(p.text)
