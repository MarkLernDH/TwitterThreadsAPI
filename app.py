import os
from dotenv import load_dotenv

from langchain import PromptTemplate, LLMChain
from langchain.agents import initialize_agent, Tool
from langchain.agents import AgentType
from langchain.chat_models import ChatOpenAI
from langchain.prompts import MessagesPlaceholder
from langchain.memory import ConversationSummaryBufferMemory
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.summarize import load_summarize_chain
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
from bs4 import BeautifulSoup
import requests
import json
from langchain.schema import SystemMessage
from fastapi import FastAPI

load_dotenv()
brwoserless_api_key = os.getenv("BROWSERLESS_API_KEY")
serper_api_key = os.getenv("SERP_API_KEY")

# 1. Tool for search


def search(query):
    url = "https://google.serper.dev/search"

    payload = json.dumps({
        "q": query
    })

    headers = {
        'X-API-KEY': serper_api_key,
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, headers=headers, data=payload)

    print(response.text)

    return response.text


# 2. Tool for scraping
def scrape_website(objective: str, url: str):
    # scrape website, and also will summarize the content based on objective if the content is too large
    # objective is the original objective & task that user give to the agent, url is the url of the website to be scraped

    print("Scraping website...")
    # Define the headers for the request
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'application/json',
    }

    # Define the data to be sent in the request
    data = {
        "url": url
    }

    # Convert Python object to JSON string
    data_json = json.dumps(data)

    # Send the POST request
    post_url = f"https://chrome.browserless.io/content?token={brwoserless_api_key}"
    response = requests.post(post_url, headers=headers, data=data_json)
    
    # Check the response status code
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, "html.parser")
        for script in soup(["script", "style"]):
            script.decompose()
        text = soup.get_text()
        print("CONTENTTTTTT:", text)

        if len(text) > 10000:
            output = summary(objective, text)
            
            return output
        else:
            return text
    else:
        print(f"HTTP request failed with status code {response.status_code}")



def summary(objective, content):
    llm = ChatOpenAI(temperature=0, model="gpt-3.5-turbo")

    text_splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n"], chunk_size=10000, chunk_overlap=500)
    docs = text_splitter.create_documents([content])
    map_prompt = """
    Extract the key information for the following text for {objective}. The text is Scraped data from a website so 
    will have a lot of usless information that doesnt relate to this topic, links, other news stories etc.. 
    Only summarise the relevant Info and try to keep as much factual information Intact
    Do not describe what the webpage is, you are here to get acurate and specific information
    Example of what NOT to do: "Investor's Business Daily: Investor's Business Daily provides news and trends on AI stocks and artificial intelligence. They cover the latest updates on AI stocks and the trends in artificial intelligence. You can stay updated on AI stocks and trends at [AI News: Artificial Intelligence Trends And Top AI Stocks To Watch "
    Here is the text:

    "{text}"
    SUMMARY:
    """
    map_prompt_template = PromptTemplate(
        template=map_prompt, input_variables=["text", "objective"])

    summary_chain = load_summarize_chain(
        llm=llm,
        chain_type='map_reduce',
        map_prompt=map_prompt_template,
        combine_prompt=map_prompt_template,
        verbose=True
    )

    output = summary_chain.run(input_documents=docs, objective=objective)

    return output

class ScrapeWebsiteInput(BaseModel):
    """Inputs for scrape_website"""
    objective: str = Field(
        description="The objective & task that users give to the agent")
    url: str = Field(description="The url of the website to be scraped")


class ScrapeWebsiteTool(BaseTool):
    name = "scrape_website"
    description = "useful when you need to get data from a website url, passing both url and objective to the function; DO NOT make up any url, the url should only be from the search results"
    args_schema: Type[BaseModel] = ScrapeWebsiteInput

    def _run(self, objective: str, url: str):
        return scrape_website(objective, url)

    def _arun(self, url: str):
        raise NotImplementedError("error here")


# 3. Create langchain agent with the tools above
tools = [
    Tool(
        name="Search",
        func=search,
        description="useful for when you need to answer questions about current events, data. You should ask targeted questions"
    ),
    ScrapeWebsiteTool(),
]

system_message = SystemMessage(
content="""You are a world class researcher, who can do detailed research on any topic and produce facts based results; 
            you do not make things up, you will try as hard as possible to gather facts & data to back up the research
            
            Please make sure you complete the objective above with the following rules:
            1/ You should do enough research to gather as much information as possible about the objective
            2/ If there are url of relevant links & articles, you will scrape it to gather more information
            3/ After scraping & search, you should think "is there any new things i should search & scraping based on the data I collected to increase research quality?" If answer is yes, continue; But don't do this more than 3 iteratins
            4/ You should not make things up, you should only write facts & data that you have gathered
            5/ In the final output, You should include all reference data & links to back up your research; You should include all reference data & links to back up your research
            6/ Always look at the web first
            7/ Output as much information as possible, make sure your answer is at least 500 WORDS
            8/ Be specific about your reasearch, do not just point to a website and say things can be found here, that what you are for
            

            Example of what NOT to do return these are just a summary of whats on the website an nothing specific, these tell the user nothing!!

            1/WIRED - WIRED provides the latest news, articles, photos, slideshows, and videos related to artificial intelligence. Source: WIRED

            2/Artificial Intelligence News - This website offers the latest AI news and trends, along with industry research and reports on AI technology. Source: Artificial Intelligence News
            """
)

agent_kwargs = {
    "extra_prompt_messages": [MessagesPlaceholder(variable_name="memory")],
    "system_message": system_message,
}

llm = ChatOpenAI(temperature=0, model="gpt-4")
memory = ConversationSummaryBufferMemory(
    memory_key="memory", return_messages=True, llm=llm, max_token_limit=1000)

agent = initialize_agent(
    tools,
    llm,
    agent=AgentType.OPENAI_FUNCTIONS,
    verbose=True,
    agent_kwargs=agent_kwargs,
    memory=memory,
)


template = """
You are an accomplished ghostwriter known for crafting LinkedIn posts that resonate with a wide professional audience. Your mission is to use the provided {subject} and {information} to compose a post that captivates and engages, mirroring the successful style and structure of high-impact LinkedIn content.

Your guide for writing the post should follow these stylistic cues:

1. Opening:
   - Begin with a compelling first line that hooks the reader, possibly posing a thought-provoking question or a bold statement related to the {subject}.

2. Tone and Style:
   - Keep the tone professional, yet personal and conversational, as if sharing insights over coffee with a peer.
   - Weave in a narrative element by relating to your own experiences or making it relatable to a wide audience.

3. Engagement Strategy:
   - Use emojis sparingly to highlight key emotions or to punctuate important points, aiding in the readability and friendliness of the post.
   - Introduce a question early on to prompt readers' curiosity and encourage comments.

4. Content Flow:
   - Structure the post in short, punchy paragraphs, separated by clear line breaks, to maintain a natural reading rhythm.
   - Incorporate line breaks before a change in thought or to create emphasis on a new idea, akin to a pause in a conversation.

5. Call to Action:
   - Towards the end, include a direct and clear call to action, such as asking for opinions, sharing the post, or encouraging sign-ups if relevant.

6. Concluding Remarks:
   - End with a closing statement that reinforces the central message, offers a summary insight, or shares anticipation for future developments.

7. Formatting:
   - Utilize bullet points for lists or key takeaways to make the information digestible.
   - Bold or italicize important terms to draw attention and aid skimming.

8. Hashtags and Links:
   - Use one or two relevant hashtags to categorize the post and improve discoverability.
   - Provide links only when they add significant value to the post, placed at the end or in the comments.

Final Instructions:
Ensure that the post is balanced, reflecting the professional context of LinkedIn while also being dynamic and personable. The language should be tailored to engage a diverse professional audience, including executives, peers, and industry newcomers. With each post, strive to create value through content that informs, challenges, and inspires.

Subject Headline: {subject}
Information: {information}


    """
prompt = PromptTemplate(
    input_variables=["info","topic"], template=template
)

llm = ChatOpenAI(model_name="gpt-4-1106-preview")
llm_chain = LLMChain(
    llm=llm,
    prompt=prompt,
    verbose=True,
    
)



# 5. Set this as an API endpoint via FastAPI
app = FastAPI()


class Query(BaseModel):
    query: str


@app.post("/")
def researchAgent( query: Query):
    query = query.query
    content = agent({"input": query})
    actual_content = content['output']
    thread = llm_chain.predict(info = actual_content, topic = query)
    return thread