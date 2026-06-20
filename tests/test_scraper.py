import unittest

from bs4 import BeautifulSoup

from scraper import _extract_bidders, _extract_estimated_price


class ScraperTests(unittest.TestCase):
    def test_extracts_bidders_from_multiline_table(self):
        html = """
        <html>
          <body>
            <table>
              <tr>
                <th>Entreprise</th>
                <th>Enveloppes administratives</th>
                <th>Enveloppes financières</th>
                <th colspan="2">Offre financière</th>
              </tr>
              <tr>
                <th></th>
                <th></th>
                <th></th>
                <th>Prix avant correction</th>
                <th>Prix après correction</th>
              </tr>
              <tr>
                <td>Societe Alpha</td>
                <td>Admissible</td>
                <td>Admissible</td>
                <td>100 000,00</td>
                <td>98 000,00</td>
              </tr>
              <tr>
                <td>Societe Beta</td>
                <td>Admissible</td>
                <td>Admissible</td>
                <td>102 000,00</td>
                <td>101 500,00</td>
              </tr>
            </table>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")

        bidders = _extract_bidders(soup)

        self.assertEqual(len(bidders), 2)
        self.assertEqual(bidders[0].name, "Societe Alpha")
        self.assertEqual(bidders[0].price, 98000.0)
        self.assertEqual(bidders[1].price, 101500.0)

    def test_extracts_estimation_from_labeled_span(self):
        html = """
        <html>
          <body>
            <div>
              Estimation TTC
              <span id="ctl0_ContentPlaceHolder1_labelReferentielZoneText">150 200,00</span>
            </div>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "lxml")

        estimated_price, currency = _extract_estimated_price(soup)

        self.assertEqual(estimated_price, 150200.0)
        self.assertEqual(currency, "MAD TTC")


if __name__ == "__main__":
    unittest.main()
