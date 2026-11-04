from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.table_class = None
        self.in_row = False
        self.in_cell = False
        self.row = []
        self.rows = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'table':
            self.table_class = attrs.get('class', '')
        elif tag == 'tr' and self.table_class:
            self.in_row = True
            self.row = []
        elif tag in ('th', 'td') and self.in_row:
            self.in_cell = True
            self.row.append('')

    def handle_data(self, data):
        if self.in_cell:
            self.row[-1] += data.strip()

    def handle_endtag(self, tag):
        if tag in ('th', 'td'):
            self.in_cell = False
        elif tag == 'tr' and self.in_row:
            self.rows.append((self.table_class, self.row))
            self.in_row = False
        elif tag == 'table':
            self.table_class = None


class EventContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (Path(__file__).resolve().parent.parent / 'dist/index.html').read_text(encoding='utf-8')
        cls.parser = TableParser()
        cls.parser.feed(cls.html)

    def test_schedule_durations_match_clock_times(self):
        rows = [row for kind, row in self.parser.rows if kind == 'schedule-table' and row and re.match(r'\d\d:\d\d', row[0])]
        self.assertEqual(len(rows), 12)
        for clock_range, duration, _activity in rows:
            start, end = clock_range.split('–')
            minutes = int((datetime.strptime(end, '%H:%M') - datetime.strptime(start, '%H:%M')).total_seconds() / 60)
            self.assertEqual(minutes, int(duration.split()[0]), clock_range)
        self.assertTrue(any(row[0] == '13:40–16:10' and row[1] == '150 min' for row in rows))

    def test_awards_and_scoring_are_complete(self):
        rows = [row for kind, row in self.parser.rows if kind == 'prize-table']
        self.assertEqual([r[:2] for r in rows[1:]], [['冠军', '1 队'], ['亚军', '1 队'], ['季军', '1 队'], ['优秀奖', '7 队'], ['参与奖', '到场参赛队伍']])
        self.assertEqual(sum(int(n) for n in re.findall(r'<strong>(\d+)%</strong>', self.html)), 100)
        self.assertIn('严禁抄袭', self.html)
        self.assertEqual(len(self.parser.ids), len(set(self.parser.ids)))
        self.assertTrue({'mode', 'agenda', 'awards', 'winners', 'flow', 'rules', 'criteria'}.issubset(self.parser.ids))

    def test_kiro_learning_resources_are_available(self):
        for item in ('Spec 驱动开发', '智能体协作', 'Hooks 自动化', 'Kiro IDE', 'Kiro CLI', 'Kiro Web', 'Kiro Crew', 'Kiro Mobile', '上手必读', '上手直播回放'):
            self.assertIn(item, self.html)


if __name__ == '__main__':
    unittest.main()
