import unittest
from unittest.mock import Mock, patch

from rss_analyzer.stream_strategy import (
    STRATEGY_QUICK_CLEAR,
    STRATEGY_RADAR,
    _llm_interpret_candidates,
    _llm_summarize_theme_groups,
    determine_stream_strategy,
    generate_stream_overview,
)


class TestStreamStrategy(unittest.TestCase):
    def setUp(self):
        self.theme_summary_patcher = patch(
            "rss_analyzer.stream_strategy._llm_summarize_theme_groups",
            return_value={},
        )
        self.candidate_interpret_patcher = patch(
            "rss_analyzer.stream_strategy._llm_interpret_candidates",
            return_value={},
        )
        self.theme_summary_patcher.start()
        self.candidate_interpret_patcher.start()

    def tearDown(self):
        self.theme_summary_patcher.stop()
        self.candidate_interpret_patcher.stop()

    @patch("rss_analyzer.stream_strategy.logger")
    @patch("rss_analyzer.stream_strategy._get_radar_client")
    def test_llm_summarize_theme_groups_logs_start_and_finish(
        self, mock_get_radar_client, mock_logger
    ):
        self.theme_summary_patcher.stop()
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"bucket摘要映射":{"程序员":"主题摘要"}}'))]
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = response
        mock_get_radar_client.return_value = (mock_client, "test-model")

        result = _llm_summarize_theme_groups(
            [
                {
                    "bucket": "程序员",
                    "count": 1,
                    "representatives": [{"title": "t1", "summary": "s1"}],
                }
            ]
        )

        self.assertEqual(result, {"程序员": "主题摘要"})
        info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
        self.assertIn("Process Stream: summarizing %s theme groups...", info_messages)
        self.assertIn("Process Stream: finished theme group summarization.", info_messages)
        self.theme_summary_patcher.start()

    @patch("rss_analyzer.stream_strategy.logger")
    @patch("rss_analyzer.stream_strategy._get_radar_client")
    def test_llm_interpret_candidates_logs_start_and_finish(
        self, mock_get_radar_client, mock_logger
    ):
        self.candidate_interpret_patcher.stop()
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"candidate解读映射":{"1":"值得一看"}}'))]
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = response
        mock_get_radar_client.return_value = (mock_client, "test-model")

        result = _llm_interpret_candidates(
            [{"id": "1", "bucket": "程序员", "title": "t1", "summary": "s1"}]
        )

        self.assertEqual(result, {"1": "值得一看"})
        info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
        self.assertIn(
            "Process Stream: interpreting %s must-read candidates...",
            info_messages,
        )
        self.assertIn("Process Stream: finished candidate interpretation.", info_messages)
        self.candidate_interpret_patcher.start()

    def test_determine_stream_strategy_uses_quick_clear_for_36kr(self):
        strategy = determine_stream_strategy(
            "feed/http://www.36kr.com/feed", "Feed: 36氪"
        )
        self.assertEqual(strategy, STRATEGY_QUICK_CLEAR)

    def test_generate_stream_overview_groups_v2ex_by_title_prefix(self):
        articles = [
            {
                "id": "1",
                "title": "[程序员] GLM 5.1 有实际测试过的吗",
                "link": "https://www.v2ex.com/t/1",
                "origin": "V2EX",
                "summary": "模型评测讨论",
                "published": 4102444800000,
            },
            {
                "id": "2",
                "title": "[推广] 我们的中转站也上线了",
                "link": "https://www.v2ex.com/t/2",
                "origin": "V2EX",
                "summary": "商业推广",
                "published": 4102444800000,
            },
            {
                "id": "3",
                "title": "[分享创造] 新项目发布",
                "link": "https://www.v2ex.com/t/3",
                "origin": "V2EX",
                "summary": "产品发布说明",
                "published": 4102444800000,
            },
        ]

        result = generate_stream_overview(
            articles,
            stream_id="feed/v2ex",
            stream_label="Feed: V2EX",
            days=3,
        )

        self.assertEqual(result["strategy"], STRATEGY_RADAR)
        buckets = {group["bucket"] for group in result["theme_groups"]}
        self.assertIn("程序员", buckets)
        self.assertIn("分享创造", buckets)
        self.assertIn("推广", buckets)
        self.assertEqual(result["mark_read_candidates"], ["2"])
        self.assertTrue(result["worth_expanding_items"][0]["link"].startswith("https://"))
        self.assertTrue(result["worth_expanding_items"][0]["interpretation"])
        self.assertIn("解读:", result["markdown"])
        self.assertIn("## Must Read", result["markdown"])
        self.assertIn("digest", result)
        self.assertIn("must_read_candidates", result["digest"])
        self.assertIn("skim_items", result["digest"])

    def test_generate_stream_overview_quick_clear_marks_newsflash_candidates(self):
        articles = [
            {
                "id": "1",
                "title": "36Kr 快讯 1",
                "link": "https://36kr.com/newsflashes/123",
                "origin": "36Kr",
                "summary": "快讯",
                "published": 4102444800000,
            },
            {
                "id": "2",
                "title": "36Kr 正文",
                "link": "https://36kr.com/p/456",
                "origin": "36Kr",
                "summary": "正文",
                "published": 4102444800000,
            },
        ]

        result = generate_stream_overview(
            articles,
            stream_id="feed/http://www.36kr.com/feed",
            stream_label="Feed: 36氪",
            strategy=STRATEGY_QUICK_CLEAR,
            days=3,
        )

        self.assertEqual(result["strategy"], STRATEGY_QUICK_CLEAR)
        self.assertEqual(result["mark_read_candidates"], ["1"])
        self.assertEqual(len(result["worth_expanding_items"]), 1)
        self.assertIn("clear_items", result["digest"])

    def test_generate_stream_overview_groups_xueqiu_by_investment_semantics(self):
        articles = [
            {
                "id": "1",
                "title": "跟仓雪球组合是否能赚钱",
                "link": "https://xueqiu.com/1",
                "origin": "雪球",
                "summary": "组合、调仓、仓位和收益讨论",
                "published": 4102444800000,
            },
            {
                "id": "2",
                "title": "黄金 ETF 与红利 ETF 怎么选",
                "link": "https://xueqiu.com/2",
                "origin": "雪球",
                "summary": "ETF、基金和宽基配置比较",
                "published": 4102444800000,
            },
            {
                "id": "3",
                "title": "华尔街上调衰退概率，市场风险怎么变",
                "link": "https://xueqiu.com/3",
                "origin": "雪球",
                "summary": "宏观、衰退、美联储和市场风险",
                "published": 4102444800000,
            },
        ]

        result = generate_stream_overview(
            articles,
            stream_id="feed/xueqiu",
            stream_label="Feed: 雪球",
            days=3,
        )

        buckets = {group["bucket"] for group in result["theme_groups"]}
        self.assertIn("策略 / 组合", buckets)
        self.assertIn("ETF / 基金", buckets)
        self.assertIn("宏观 / 市场", buckets)

    @patch(
        "rss_analyzer.stream_strategy._llm_interpret_candidates",
        return_value={"1": "这条能快速判断工具讨论有没有新信息"},
    )
    @patch(
        "rss_analyzer.stream_strategy._llm_summarize_theme_groups",
        return_value={"程序员": "最近主要在讨论模型工具和开发实践。"},
    )
    def test_generate_stream_overview_prefers_llm_theme_and_candidate_text(
        self, mock_theme_summary, mock_candidate_interpretation
    ):
        articles = [
            {
                "id": "1",
                "title": "[程序员] GLM 5.1 有实际测试过的吗",
                "link": "https://www.v2ex.com/t/1",
                "origin": "V2EX",
                "summary": "模型评测讨论",
                "published": 4102444800000,
            }
        ]

        result = generate_stream_overview(
            articles,
            stream_id="feed/v2ex",
            stream_label="Feed: V2EX",
            days=3,
        )

        self.assertEqual(result["theme_groups"][0]["summary"], "最近主要在讨论模型工具和开发实践。")
        self.assertEqual(
            result["worth_expanding_items"][0]["interpretation"],
            "这条能快速判断工具讨论有没有新信息",
        )
        mock_theme_summary.assert_called_once()
        mock_candidate_interpretation.assert_called_once()

    def test_generate_stream_overview_groups_jisilu_by_convertible_bond_semantics(self):
        articles = [
            {
                "id": "1",
                "title": "可转债双低策略本周怎么调",
                "link": "https://www.jisilu.cn/1",
                "origin": "集思录",
                "summary": "转债、双低、强赎和回售讨论",
                "published": 4102444800000,
            },
            {
                "id": "2",
                "title": "ETF 折价套利今天还有没有空间",
                "link": "https://www.jisilu.cn/2",
                "origin": "集思录",
                "summary": "ETF、LOF、折价溢价和套利",
                "published": 4102444800000,
            },
            {
                "id": "3",
                "title": "低佣开户和券商免五怎么选",
                "link": "https://www.jisilu.cn/3",
                "origin": "集思录",
                "summary": "开户、佣金、免五和账户规则",
                "published": 4102444800000,
            },
        ]

        result = generate_stream_overview(
            articles,
            stream_id="feed/jisilu",
            stream_label="Feed: 集思录",
            days=3,
        )

        buckets = {group["bucket"] for group in result["theme_groups"]}
        self.assertIn("可转债", buckets)
        self.assertIn("ETF / LOF / 套利", buckets)
        self.assertIn("券商 / 账户 / 规则", buckets)
        self.assertEqual(result["mark_read_candidates"], ["3"])


if __name__ == "__main__":
    unittest.main()
