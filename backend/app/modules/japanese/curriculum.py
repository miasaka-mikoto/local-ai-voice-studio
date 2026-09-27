from __future__ import annotations

from copy import deepcopy
from typing import Any


CATALOG_VERSION = "2026.08.daily-life-v1"


STAGES: tuple[dict[str, Any], ...] = (
    {
        "id": "foundation",
        "order": 1,
        "title": "生存基础",
        "level_range": "N5",
        "outcome": "能完成自我介绍、购买、点餐、问路和时间确认。",
        "weekly_shape": {"conversation": 2, "shadowing": 2, "review": 3},
    },
    {
        "id": "daily_independence",
        "order": 2,
        "title": "独立生活",
        "level_range": "N4",
        "outcome": "能独立处理交通、购物、预约、住宿和基础医疗。",
        "weekly_shape": {"conversation": 3, "shadowing": 2, "review": 3},
    },
    {
        "id": "social_work",
        "order": 3,
        "title": "社会与职场",
        "level_range": "N3",
        "outcome": "能说明问题、协商安排并在学校、职场和公共机构沟通。",
        "weekly_shape": {"conversation": 3, "shadowing": 3, "review": 4},
    },
    {
        "id": "advanced_life",
        "order": 4,
        "title": "复杂现实沟通",
        "level_range": "N2–N1",
        "outcome": "能处理投诉、正式说明、面试、灾害和观点讨论。",
        "weekly_shape": {"conversation": 3, "shadowing": 3, "review": 5},
    },
)


def _scenario(
    scenario_id: str,
    stage_id: str,
    level: str,
    domain: str,
    title: str,
    japanese_title: str,
    objective: str,
    grammar: tuple[str, ...],
    samples: tuple[str, str],
    prerequisites: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "stage_id": stage_id,
        "level": level,
        "domain": domain,
        "title": title,
        "japanese_title": japanese_title,
        "objective": objective,
        "grammar_targets": list(grammar),
        "sample_utterances": list(samples),
        "prerequisites": list(prerequisites),
        "lesson_steps": ["输入示范", "关键词替换", "半开放角色扮演", "无提示实战", "错项复习"],
        "completion_policy": {
            "minimum_turns": 3,
            "requires_manual_complete": True,
            "meaning": "完成表示已走完场景练习，不代表自动判定语言能力已掌握。",
        },
    }


SCENARIOS: tuple[dict[str, Any], ...] = (
    _scenario("self-introduction", "foundation", "N5", "social", "初次见面", "はじめまして", "说清姓名、来自哪里和兴趣", ("～です", "～から来ました", "～が好きです"), ("はじめまして、李と申します。", "中国から来ました。よろしくお願いします。")),
    _scenario("home-morning", "foundation", "N5", "home", "居家晨间", "朝の生活", "描述起床、早餐和出门安排", ("～時に", "～てから", "～ます"), ("七時に起きます。", "朝ご飯を食べてから出かけます。")),
    _scenario("convenience-store", "foundation", "N5", "shopping", "便利店结账", "コンビニで会計", "询问价格、袋子和支付方式", ("これをください", "～はいくらですか", "～で払います"), ("これを一つください。", "袋は要りません。カードで払います。")),
    _scenario("cafe-order", "foundation", "N5", "food", "咖啡店点单", "カフェで注文", "礼貌点单并选择冷热和尺寸", ("～をください", "～にします", "一つ／二つ"), ("ホットコーヒーを一つください。", "Mサイズにします。"), prerequisites=("convenience-store",)),
    _scenario("station-ticket", "foundation", "N5", "transport", "车站买票", "駅で切符を買う", "说明目的地、张数并确认站台", ("～まで", "～枚", "何番線"), ("新宿まで一枚お願いします。", "この電車は何番線ですか。")),
    _scenario("ask-directions", "foundation", "N5", "transport", "街头问路", "道を聞く", "询问地点并听懂左右、直行和距离", ("～はどこですか", "～てください", "右／左"), ("駅はどこですか。", "次の角を右に曲がってください。"), prerequisites=("station-ticket",)),
    _scenario("supermarket", "foundation", "N5", "shopping", "超市采购", "スーパーで買い物", "询问商品位置、数量和是否有库存", ("～はありますか", "どこ", "～個"), ("牛乳はどこにありますか。", "りんごを三個ください。"), prerequisites=("convenience-store",)),
    _scenario("restaurant", "foundation", "N5", "food", "餐厅用餐", "レストラン", "入座、点餐、追加和结账", ("～をお願いします", "まだです", "お会計"), ("二人です。窓側の席をお願いします。", "お会計をお願いします。"), prerequisites=("cafe-order",)),
    _scenario("time-appointment", "foundation", "N5", "services", "确认时间", "時間を確認する", "约定日期时间并确认迟到", ("～時から", "～てもいいですか", "何曜日"), ("金曜日の三時からでいいですか。", "十分遅れてもいいですか。")),
    _scenario("weather-smalltalk", "foundation", "N5", "social", "天气寒暄", "天気の話", "用天气开启和结束短对话", ("～ですね", "～そうです", "今日は"), ("今日は暑いですね。", "午後は雨が降りそうです。"), prerequisites=("self-introduction",)),

    _scenario("train-transfer", "daily_independence", "N4", "transport", "换乘与误点", "乗り換えと遅延", "确认换乘、末班车、误点原因和替代路线", ("～ばいいですか", "～そうです", "～ため"), ("渋谷へはどこで乗り換えればいいですか。", "電車が遅れているため、別の路線を使います。"), prerequisites=("station-ticket",)),
    _scenario("bus-taxi", "daily_independence", "N4", "transport", "公交与出租车", "バスとタクシー", "确认下车站、路线和大致费用", ("～までお願いします", "～で降ります", "どのくらい"), ("市役所までお願いします。", "次の停留所で降ります。"), prerequisites=("ask-directions",)),
    _scenario("clothes-shopping", "daily_independence", "N4", "shopping", "服装试穿", "服を試着する", "说明尺寸颜色、试穿并比较", ("～てみてもいいですか", "～すぎる", "ほうが"), ("これを試着してもいいですか。", "もう少し大きいほうがいいです。"), prerequisites=("supermarket",)),
    _scenario("return-exchange", "daily_independence", "N4", "shopping", "退换商品", "返品と交換", "解释问题、出示小票并提出解决方案", ("～てしまいました", "～ので", "交換できますか"), ("サイズを間違えてしまいました。", "レシートがあるので、交換できますか。"), prerequisites=("clothes-shopping",)),
    _scenario("delivery", "daily_independence", "N4", "home", "快递收发", "宅配便", "改配送时间、说明地址和未收到包裹", ("～てもらえますか", "届いていません", "～の予定"), ("配達時間を変更してもらえますか。", "荷物がまだ届いていません。"), prerequisites=("time-appointment",)),
    _scenario("hotel-checkin", "daily_independence", "N4", "travel", "酒店入住", "ホテルのチェックイン", "核对预约、早餐、设施和退房", ("予約してあります", "～は含まれていますか", "利用できますか"), ("李の名前で予約してあります。", "朝食は料金に含まれていますか。"), prerequisites=("restaurant",)),
    _scenario("clinic-reception", "daily_independence", "N4", "health", "医院挂号", "病院の受付", "预约、填写信息并说明主要症状", ("～たいんですが", "～から", "～があります"), ("診察を受けたいんですが。", "昨日から熱があります。"), prerequisites=("time-appointment",)),
    _scenario("pharmacy", "daily_independence", "N4", "health", "药店咨询", "薬局で相談", "说明症状、过敏和服药方式", ("～に効く", "～たことがあります", "～回"), ("喉の痛みに効く薬はありますか。", "この薬は一日に何回飲みますか。"), prerequisites=("clinic-reception",)),
    _scenario("phone-reservation", "daily_independence", "N4", "services", "电话预约", "電話で予約", "电话开场、预约、更改和复述信息", ("～をお願いしたい", "～でよろしいですか", "変更したい"), ("明日の予約をお願いしたいんですが。", "念のため、時間をもう一度お願いします。"), prerequisites=("time-appointment",)),
    _scenario("friend-plans", "daily_independence", "N4", "social", "朋友邀约", "友達と予定を決める", "邀请、婉拒、提出替代时间", ("～ない？", "～なら", "～ことにしよう"), ("今週末、一緒に映画を見ない？", "土曜日なら空いているよ。"), prerequisites=("weather-smalltalk",)),

    _scenario("office-onboarding", "social_work", "N3", "work", "职场报到", "初出勤", "正式自我介绍、确认职责和请教流程", ("～ことになりました", "～させていただきます", "～について"), ("本日から勤務することになりました李です。", "業務の流れについて教えていただけますか。"), prerequisites=("self-introduction",)),
    _scenario("meeting", "social_work", "N3", "work", "参加会议", "会議に参加する", "表达同意、保留意见和确认行动项", ("～と考えます", "～のではないでしょうか", "～という理解"), ("その案に賛成ですが、納期が課題だと考えます。", "私が資料を更新するという理解でよろしいですか。"), prerequisites=("office-onboarding",)),
    _scenario("work-report", "social_work", "N3", "work", "汇报问题", "問題を報告する", "按事实、影响、已做处理和请求支援汇报", ("～ところ", "～により", "～ていただけますか"), ("確認したところ、データに不一致がありました。", "本日中の確認にご協力いただけますか。"), prerequisites=("office-onboarding",)),
    _scenario("school-office", "social_work", "N3", "school", "学校事务", "学校の事務室", "咨询选课、证明、缺席和截止日期", ("～に関して", "～までに", "発行していただく"), ("履修登録に関して確認したいことがあります。", "在学証明書を発行していただけますか。"), prerequisites=("phone-reservation",)),
    _scenario("bank-post", "social_work", "N3", "services", "银行与邮局", "銀行と郵便局", "开户、汇款、寄件并确认手续费", ("～を開設したい", "～宛て", "手数料"), ("普通口座を開設したいです。", "この荷物を中国宛てに送りたいです。"), prerequisites=("delivery",)),
    _scenario("city-hall", "social_work", "N3", "services", "市役所办事", "市役所の手続き", "说明办理事项、材料缺失和后续步骤", ("～の手続き", "～が必要", "～場合"), ("転入届の手続きをしたいです。", "書類が足りない場合はどうすればいいですか。"), prerequisites=("bank-post",)),
    _scenario("housing-contract", "social_work", "N3", "home", "租房签约", "賃貸契約", "询问费用、条款、入住条件和解约", ("～ことになっています", "～に含まれる", "解約"), ("管理費は家賃に含まれていますか。", "解約する場合は何日前までに連絡しますか。"), prerequisites=("hotel-checkin",)),
    _scenario("home-repair", "social_work", "N3", "home", "报修协商", "修理を依頼する", "描述故障、影响、可上门时间和责任", ("～なくなりました", "～てもらいたい", "～可能性"), ("昨日からお湯が出なくなりました。", "明日の午前中に見てもらいたいです。"), prerequisites=("housing-contract",)),
    _scenario("neighbor-issue", "social_work", "N3", "social", "邻里沟通", "近所の相談", "礼貌提出噪音、垃圾和公共空间问题", ("恐れ入りますが", "～ていただけないでしょうか", "～ようです"), ("恐れ入りますが、夜は音量を下げていただけないでしょうか。", "ごみの曜日が違うようです。"), prerequisites=("housing-contract",)),
    _scenario("team-game", "social_work", "N3", "hobby", "组队协作", "ゲームで連携", "快速分工、报告状态、复盘失误", ("～ておく", "～うちに", "～せいで"), ("私が前を守るので、回復をお願いします。", "敵が来る前に準備しておきましょう。"), prerequisites=("friend-plans",)),

    _scenario("doctor-detail", "advanced_life", "N2", "health", "详细就诊", "診察で詳しく説明", "按时间线说明症状、程度、诱因和病史", ("～に伴って", "～に限らず", "～わけではない"), ("運動した時に限らず、安静にしていても痛みます。", "発熱に伴って関節も痛くなりました。"), prerequisites=("clinic-reception", "pharmacy")),
    _scenario("emergency-disaster", "advanced_life", "N2", "safety", "紧急与灾害", "緊急時と災害", "报警、说明位置伤情并听从避难指示", ("～おそれがある", "～次第", "～に備えて"), ("けが人がいるおそれがあります。", "安全を確認し次第、避難所へ向かいます。"), prerequisites=("doctor-detail",)),
    _scenario("customer-complaint", "advanced_life", "N2", "services", "客户投诉", "苦情を伝える", "客观说明经过、损失、期望与可接受方案", ("～にもかかわらず", "～ざるを得ない", "～を求めます"), ("連絡したにもかかわらず、商品が届いていません。", "状況の説明と返金を求めます。"), prerequisites=("return-exchange", "delivery")),
    _scenario("job-interview", "advanced_life", "N2", "work", "求职面试", "就職面接", "用具体证据说明经历、动机、优势和不足", ("～を通じて", "～に貢献する", "～を踏まえて"), ("前職の経験を通じて、調整力を身につけました。", "御社の海外事業に貢献したいと考えています。"), prerequisites=("meeting", "work-report")),
    _scenario("negotiation", "advanced_life", "N2", "work", "条件协商", "条件を交渉する", "确认利益、提出条件、让步和总结共识", ("～を前提に", "～であれば", "折り合い"), ("納期を延ばすことを前提に、この価格で対応できます。", "数量が増えるのであれば、再検討します。"), prerequisites=("meeting",)),
    _scenario("formal-apology", "advanced_life", "N2", "work", "正式道歉", "正式に謝罪する", "承担责任、说明原因、补救和防止再发", ("～により", "～ことをお詫び", "再発防止"), ("当方の確認不足により、ご迷惑をおかけしました。", "再発防止策を本日中にご報告します。"), prerequisites=("work-report",)),
    _scenario("news-opinion", "advanced_life", "N1", "society", "新闻与观点", "ニュースについて議論", "区分事实与观点、比较依据并回应反方", ("～にすぎない", "～をめぐって", "一方で"), ("その数字は一つの側面を示しているにすぎません。", "利便性が高まる一方で、格差も課題です。"), prerequisites=("meeting",)),
    _scenario("community-event", "advanced_life", "N1", "society", "社区协作", "地域活動に参加", "提出方案、协调分歧并主持共识", ("～を踏まえ", "～に越したことはない", "～を図る"), ("住民の意見を踏まえ、時間帯を見直しましょう。", "安全確保を図るため、担当を決めます。"), prerequisites=("neighbor-issue", "news-opinion")),
)


def catalog() -> dict[str, Any]:
    return {
        "version": CATALOG_VERSION,
        "stages": deepcopy(list(STAGES)),
        "scenarios": deepcopy(list(SCENARIOS)),
        "coverage": {
            "scenario_count": len(SCENARIOS),
            "domains": sorted({item["domain"] for item in SCENARIOS}),
            "levels": ["N5", "N4", "N3", "N2", "N1"],
            "scope_note": "覆盖高频日常、公共服务、医疗、学校、职场、社交、灾害与复杂沟通；不是对现实中无限情境的穷举。",
        },
    }


def scenario_index() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in SCENARIOS}


def validate_catalog() -> None:
    stage_ids = {item["id"] for item in STAGES}
    scenarios = scenario_index()
    if len(scenarios) != len(SCENARIOS):
        raise RuntimeError("Japanese curriculum contains duplicate scenario ids")
    for scenario in SCENARIOS:
        if scenario["stage_id"] not in stage_ids:
            raise RuntimeError(f"Unknown stage for scenario {scenario['id']}")
        for prerequisite in scenario["prerequisites"]:
            if prerequisite not in scenarios:
                raise RuntimeError(f"Unknown prerequisite {prerequisite} for {scenario['id']}")


validate_catalog()
