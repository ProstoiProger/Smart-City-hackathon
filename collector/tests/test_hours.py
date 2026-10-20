import unittest
from scripts.enrich_dataset import parse_hours

class HoursTests(unittest.TestCase):
    def test_unknown_and_complex_expressions_stay_unknown(self):
        self.assertIsNone(parse_hours(None))
        self.assertIsNone(parse_hours('sunrise-sunset'))
        self.assertIsNone(parse_hours('Mo-Fr 25:00-30:00'))

    def test_unspecified_days_are_not_invented(self):
        parsed=parse_hours('Mo-Fr 09:00-18:00; Sa 10:00-14:00')
        self.assertEqual(parsed['weekly']['Mo'],[['09:00','18:00']])
        self.assertEqual(parsed['weekly']['Sa'],[['10:00','14:00']])
        self.assertIsNone(parsed['weekly']['Su'])

    def test_breaks_holidays_and_explicit_closure(self):
        parsed=parse_hours('Mo-Fr 09:00-12:00,13:00-18:00; Sa-Su off; PH off')
        self.assertEqual(parsed['weekly']['Su'],[])
        self.assertEqual(parsed['break_hours']['Mo'],[['12:00','13:00']])
        self.assertEqual(parsed['holiday_hours'],['PH off'])

    def test_russian_daily_schedule(self):
        parsed=parse_hours('с 12:00 до 23:00 ежедневно')
        self.assertEqual(parsed['weekly']['Su'],[['12:00','23:00']])

if __name__=='__main__':unittest.main()
