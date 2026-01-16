import requests
import json
from pathlib import Path
import dspy
import re
from bs4 import BeautifulSoup

from typing import List, Dict, Any, Iterator

from rich.console import Console
from approach.utils.token_logger import LLMTokenLogger
import os

console = Console(color_system=None)


class GeneratePRSummary(dspy.Signature):
    """Here are 20 strategies to generate a summary for PR (Pull Request) content, use those relevant to your use case:

    Highlight Key Changes: Focus on the most significant changes made in the PR.
    Include Issue References: Mention any issues or tickets that the PR addresses.
    List Affected Files: Summarize which files have been changed and the extent of changes.
    Describe New Features: Highlight any new features introduced by the PR.
    Bug Fixes: Clearly state any bugs that have been fixed.
    Performance Improvements: Mention any performance improvements made.
    Refactoring: Summarize any code refactoring done.
    Backward Compatibility: Note if the changes are backward compatible or not.
    Testing Summary: Include a brief summary of tests added or modified.
    Impact Analysis: Describe the potential impact of the changes on the system.
    Dependencies: Mention any new dependencies introduced or existing ones removed.
    Security Implications: Highlight any security-related changes or improvements.
    Documentation Updates: Summarize any updates to documentation.
    User Interface Changes: Describe any changes to the user interface.
    Configuration Changes: Note any changes to configuration files or settings.
    Migration Steps: If applicable, include steps for migrating to the new version.
    Known Issues: List any known issues that remain after the PR.
    Reviewer Notes: Add any additional notes or comments for the reviewers.

    Keep any relevant reference or links to the PR content.
    """

    raw_html: str = dspy.InputField(desc="Raw HTML content of the PR")
    current_draft: str = dspy.InputField(
        desc="Current draft of the summary (if available)")
    extra_info: str = dspy.InputField(
        desc="Extra information to help generate the summary")
    source_of_extra_info: str = dspy.InputField(
        desc="URL or source of the extra information")
    summary: str = dspy.OutputField(desc="Summary of the PR")


class PickRelevantLinks(dspy.Signature):
    """Pick the most relevant links to visit for more information.
    Here are 20 strategies to pick the most relevant links to visit for more information:

    Official Documentation: Prioritize links to official documentation of the technology or tool.
    Community Forums: Look for links to active community forums or discussion boards.
    Tutorials and Guides: Select links to high-quality tutorials and step-by-step guides.
    Blog Posts: Choose blog posts from reputable sources or experts in the field.
    Research Papers: Include links to relevant research papers or academic articles.
    Video Tutorials: Pick links to video tutorials from trusted educational platforms.
    FAQs: Look for links to frequently asked questions pages.
    Release Notes: Include links to release notes for the latest updates.
    GitHub Repositories: Select links to relevant GitHub repositories.
    API References: Prioritize links to API reference documentation.
    Case Studies: Look for links to case studies demonstrating real-world applications.
    Comparison Articles: Include links to articles comparing similar tools or technologies.
    Best Practices: Select links to resources outlining best practices.
    Cheat Sheets: Look for links to cheat sheets or quick reference guides.
    Forums and Q&A Sites: Include links to relevant threads on Q&A sites like Stack Overflow.
    Official Announcements: Prioritize links to official announcements or blog posts from the developers.
    Webinars and Workshops: Look for links to upcoming or recorded webinars and workshops.
    Podcasts: Include links to relevant podcast episodes.
    Social Media: Select links to relevant social media posts or threads.
    Books and eBooks: Look for links to recommended books or eBooks on the topic.

    Prefer links to specific pages or sections over general homepages.
    """

    current_pr_number: int = dspy.InputField(
        desc="Current PR number (indicative of what is already available)")
    pr_summary: str = dspy.InputField(desc="Summary of the PR")
    all_links: list[str] = dspy.InputField(
        desc="List of links available in the PR")
    relevant_links: list[str] = dspy.OutputField(
        desc="Most relevant links to visit")


class PageInfo:
    def __init__(self, page_url, initialize: bool = True):
        self.page_url = page_url
        self.summaries = []
        self.summarizer = dspy.ChainOfThought(GeneratePRSummary)
        self.provenance = [page_url]
        self.next_links = []
        self.link_picker = dspy.ChainOfThought(PickRelevantLinks)
        self.token_logger = LLMTokenLogger()
        if initialize:
            self.retrieve_page_content()
            self.generate_first_summary()

    def retrieve_page_content(self):
        page_content = self._retrieve_page_content_and_links(self.page_url)
        self.content_as_markdown = page_content["content_as_markdown"]
        self.links = list(set([
            link for link in page_content["links"] if str(link).strip() != ""]))

    def _retrieve_page_content_and_links(self, url: str) -> Dict[str, Any]:
        console.log(f"Retrieving page content from url: {url}")
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, "html.parser")
            markdown_content = self._condense_new_lines(soup.get_text())
            links = self._extract_all_links(soup)
            return {"content_as_markdown": markdown_content, "links": links}
        else:
            console.log(f"Failed to retrieve page content from {url}")
            return {"content_as_markdown": "", "links": []}

    def _condense_new_lines(self, text: str) -> str:
        return re.sub(r"\n+", "\n", text)

    def _extract_all_links(self, soup: BeautifulSoup) -> List[str]:
        links = []
        for link in soup.find_all('a'):
            links.append(link.get('href'))
        return links

    def generate_first_summary(self):
        response_summary = self.summarizer(
            current_draft="None",
            extra_info="None",
            source_of_extra_info="None",
            raw_html=self.content_as_markdown)
        self.summaries = [response_summary.summary]
        lm = dspy.settings.get("lm", None)
        if lm is not None:
            self.token_logger.log(lm=lm, stage=GeneratePRSummary)

    @property
    def summary(self):
        if not self.summaries:
            self.generate_first_summary()
        return self.summaries[-1]

    def enrich_with(self, other_page_info):
        console.log(
            f"Enriching the page {self.page_url} with {other_page_info.page_url}")
        response_summary = self.summarizer(
            current_draft=self.summary,
            extra_info=other_page_info.content_as_markdown,
            source_of_extra_info=other_page_info.page_url,
            raw_html=self.content_as_markdown)
        new_summary = response_summary.summary
        self.summaries.append(new_summary)
        lm = dspy.settings.get("lm", None)
        if lm is not None:
            self.token_logger.log(lm=lm, stage=GeneratePRSummary)
        self.provenance.append(other_page_info.page_url)

    def enrich(self, max_iterations: int = 3):
        for _ in range(max_iterations):
            if len(self.provenance) == max_iterations:
                console.log(
                    f"Reached max iterations to enrich the page {self.page_url}")
                console.log(
                    f"Pages used (n={max_iterations}): {self.provenance}")
                break
            next_url = self._pick_next_link()
            if not next_url:
                break
            try:
                # Exception Handling: some urls might be invalid/unreachable
                other_page_info = PageInfo(next_url)
            except Exception as e:
                console.log(
                    f"Failed to retrieve page content from picked url: {next_url}")
                continue
            if other_page_info:
                self.enrich_with(other_page_info)

    def _pick_next_link(self) -> str:
        if not self.next_links:
            self._decide_next_link()
        if not self.next_links:
            return None
        return self.next_links.pop(0)

    def _decide_next_link(self) -> str:
        potentially_relevant_links = self._pre_filter_links_github(
            self.links)
        potentially_relevant_links = [
            link
            for link in potentially_relevant_links
            if not link.startswith(self.page_url)
            and not link == "https://github.com"]
        # remove relative links
        potentially_relevant_links = [link
                                      for link in potentially_relevant_links
                                      if not link.startswith("/")]
        response_links = self.link_picker(
            current_pr_number=self.page_url,
            pr_summary=self.summary,
            all_links=potentially_relevant_links)
        # Log token usage for PickRelevantLinks
        lm = dspy.settings.get("lm", None)
        if lm is not None:
            self.token_logger.log(lm=lm, stage=PickRelevantLinks)
        console.log("Reasoning about links...")
        console.log(getattr(response_links, "reasoning", ""))
        llm_relevant_links = response_links.relevant_links
        self.next_links.extend(llm_relevant_links)

    def _pre_filter_links(
            self,
            links: List[str],
            prefixes_to_ignore: List[str]) -> List[str]:
        return [link for link in links if not any(
            link.startswith(prefix) for prefix in prefixes_to_ignore)]

    def _pre_filter_links_github(
            self,
            links: List[str],) -> List[str]:
        links = self._pre_filter_links(
            links,
            prefixes_to_ignore=[
                "/",  # relative links
                "#",  # internal links
                "{{",  # templated links
                "https://github.com/features",
                "https://github.co/hiddenchars",
                "https://docs.github.com",
                "https://skills.github.com",
                "https://github.blog",
                "https://github.com/enterprise",
                "https://github.com/team",
                "https://github.com/enterprise/startups",
                "https://resources.github.com/learn/pathways",
                "https://resources.github.com",
                "https://github.com/customer-stories",
                "https://partner.github.com",
                "https://github.com/solutions/executive-insights",
                "https://github.com/readme",
                "https://github.com/topics",
                "https://github.com/trending",
                "https://github.com/collections",
                "https://github.com/enterprise/advanced-security",
                "https://github.com/pricing",
                "https://github.com/security",
                "https://www.githubstatus.com/",
                "https://support.github.com",
            ])

        links = [link for link in links if not re.match(
            r"https://github.com/[a-zA-Z0-9-]+/?$", link)]
        return links

    def to_json(self, file_path: str):
        data = {
            "page_url": self.page_url,
            "content_as_markdown": self.content_as_markdown,
            "links": self.links,
            "summaries": self.summaries,
            "provenance": self.provenance,
            "token_usage": self.token_logger.get_logs_as_list()
        }
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=4)

    @classmethod
    def from_json(cls, file_path: str):
        with open(file_path, 'r') as f:
            data = json.load(f)
        instance = cls(data["page_url"], initialize=False)
        instance.content_as_markdown = data["content_as_markdown"]
        instance.links = data["links"]
        instance.summaries = data["summaries"]
        instance.provenance = data["provenance"]
        # Optionally: instance.token_logger._logs = data.get("llm_token_logs", {})
        return instance
