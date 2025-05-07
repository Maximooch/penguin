"""
Examples of using PyDoll browser tools in Penguin.

This file contains code examples for common browser automation tasks using PyDoll.
"""

import asyncio
import os
from pydoll.browser.chrome import Chrome
from pydoll.browser.options import Options
from pydoll.constants import By

from penguin.tools.pydoll_tools import (
    pydoll_browser_manager,
    PyDollBrowserNavigationTool,
    PyDollBrowserInteractionTool,
    PyDollBrowserScreenshotTool
)


# Initialize tool instances
navigation_tool = PyDollBrowserNavigationTool()
interaction_tool = PyDollBrowserInteractionTool()
screenshot_tool = PyDollBrowserScreenshotTool()


async def example_basic_navigation():
    """Basic navigation to a website."""
    # Initialize the browser
    await pydoll_browser_manager.initialize(headless=False)
    
    # Navigate to a URL
    result = await navigation_tool.execute("https://www.example.com")
    print(f"Navigation result: {result}")
    
    # Take a screenshot
    screenshot = await screenshot_tool.execute()
    print(f"Screenshot saved to: {screenshot.get('filepath')}")
    
    # Close the browser
    await pydoll_browser_manager.close()


async def example_form_filling():
    """Example of filling and submitting a form."""
    await pydoll_browser_manager.initialize(headless=False)
    
    # Navigate to a search engine
    await navigation_tool.execute("https://www.google.com")
    
    # Input text in search field
    await interaction_tool.execute(
        action="input",
        selector="input[name='q']",
        selector_type="css",
        text="PyDoll browser automation"
    )
    
    # Submit the form
    await interaction_tool.execute(
        action="submit",
        selector="form[action='/search']",
        selector_type="css"
    )
    
    # Wait for results to load
    await asyncio.sleep(2)
    
    # Take a screenshot of the results
    await screenshot_tool.execute()
    
    await pydoll_browser_manager.close()


async def example_with_custom_options():
    """Example using custom browser options."""
    # Create custom options
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    
    # For headless mode
    # options.add_argument("--headless=new")
    
    # Create a new browser instance with custom options
    browser = Chrome(options=options)
    await browser.start()
    
    # Get the page
    page = await browser.get_page()
    
    # Navigate to a URL
    await page.go_to("https://github.com/autoscrape-labs/pydoll")
    
    # Find an element by XPath
    star_button = await page.wait_element(
        By.XPATH, 
        '//a[contains(@href, "/stargazers")]',
        timeout=5,
        raise_exc=False
    )
    
    if star_button:
        print("Found star button")
        
        # Get text from the element
        text = await star_button.text
        print(f"Button text: {text}")
    else:
        print("Star button not found")
    
    # Take a screenshot
    screenshot_path = os.path.join(os.getcwd(), "github_screenshot.png")
    await page.get_screenshot(screenshot_path)
    print(f"Screenshot saved to {screenshot_path}")
    
    # Close the browser
    await browser.stop()


async def example_multiple_tabs():
    """Example of working with multiple tabs."""
    await pydoll_browser_manager.initialize(headless=False)
    
    # Get the browser and page
    browser = pydoll_browser_manager.browser
    page = await pydoll_browser_manager.get_page()
    
    # Navigate to first site
    await page.go_to("https://www.example.com")
    
    # Create a new tab
    page2 = await browser.new_page()
    await page2.go_to("https://www.github.com")
    
    # Switch back to first tab
    pages = await browser.get_pages()
    await browser.activate_page(pages[0])
    
    # Take a screenshot of the first tab
    await pages[0].get_screenshot("tab1.png")
    
    # Switch to second tab
    await browser.activate_page(pages[1])
    
    # Take a screenshot of the second tab
    await pages[1].get_screenshot("tab2.png")
    
    await pydoll_browser_manager.close()


async def example_handling_captchas():
    """Example showing how PyDoll handles captchas better than traditional webdrivers."""
    await pydoll_browser_manager.initialize(headless=False)
    
    # Navigate to a site with Cloudflare protection
    await navigation_tool.execute("https://nowsecure.nl")
    
    # Wait for the potential captcha to be solved
    await asyncio.sleep(5)
    
    # Take a screenshot to verify if we passed the protection
    await screenshot_tool.execute()
    
    await pydoll_browser_manager.close()


async def example_web_scraping():
    """Example of scraping data from a website."""
    await pydoll_browser_manager.initialize(headless=False)
    
    # Navigate to a webpage
    await navigation_tool.execute("https://quotes.toscrape.com/")
    
    # Get the page object for more advanced operations
    page = await pydoll_browser_manager.get_page()
    
    # Find all quote elements
    quote_elements = await page.find_elements(By.CSS_SELECTOR, ".quote")
    
    # Extract data from each quote
    quotes = []
    for element in quote_elements[:3]:  # Get the first 3 quotes
        text_element = await element.find_element(By.CSS_SELECTOR, ".text")
        author_element = await element.find_element(By.CSS_SELECTOR, ".author")
        
        quote_text = await text_element.text
        author = await author_element.text
        
        quotes.append({"text": quote_text, "author": author})
    
    # Print the extracted data
    for i, quote in enumerate(quotes, 1):
        print(f"Quote {i}:")
        print(f"  Text: {quote['text']}")
        print(f"  Author: {quote['author']}")
        print()
    
    await pydoll_browser_manager.close()


# Main function to run examples
async def run_examples():
    print("Running PyDoll browser examples...")
    
    # Choose which example to run
    # await example_basic_navigation()
    # await example_form_filling()
    # await example_with_custom_options()
    # await example_multiple_tabs()
    # await example_handling_captchas()
    await example_web_scraping()
    
    print("Examples completed!")


# Run the examples if this file is executed directly
if __name__ == "__main__":
    asyncio.run(run_examples()) 