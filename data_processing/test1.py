
import read_sql as rs
import os
import re
import sys
import jdy
import pandas as pd
import asyncio
from datetime import datetime, timedelta

# 模块级路径配置
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, ".."))

if project_root not in sys.path:
    sys.path.append(project_root)

from project_config.project import custom_count_sql
from data_processing.dy_video_analysis import DailyDataProcessor


def clean_title(title):
    """
    清洗作品标题：
    - 去除所有 #标签（包括前面的空格）
    - 去掉首尾空格和换行
    """
    if pd.isna(title):
        return ""
    title = re.sub(r'\s+#\S+', '', title)
    return title.strip()


class Dividend:
    def __init__(self):
        self.sql = rs.MSSQLDatabase()
        self.custom_count_path = custom_count_sql
        self.jdy = jdy.JDY()
        self.daily_process = DailyDataProcessor()
        self.metrics = ['播放量', '点赞量', '收藏量', '评论量', '分享量']

    def get_custom_count(self):
        try:
            print(f"Loading SQL from: {self.custom_count_path}")
            custom_count = self.sql.get_from_sqlfile(self.custom_count_path)
            return custom_count
        except FileNotFoundError as e:
            print(f"SQL文件未找到: {e}")
            return None
        except Exception as e:
            print(f"数据库操作失败: {e}")
            return None
    
    def upload_dy_custom(self):
        appId="67c280b7c6387c4f4afd50ae"
        entryId= "67df691887cb8026eb606a95"
        custom_data = self.get_custom_count()
        asyncio.run(self.jdy.batch_create(app_id=appId, entry_id=entryId, source_data=custom_data))

    def get_daily_video_data(self):
        return self.daily_process.get_daily_data()

    def total_money_dy(self):
        total_custom = self.get_custom_count()
        total_money = total_custom['客资数'].sum()
        return total_money * 50

    def video_dividend(self):
        video_df = self.get_daily_video_data().copy()
        video_people = self.get_video_people().copy()

        video_people = video_people.rename(columns={"正片标题": "作品名称"})
        video_df["作品名称"] = video_df["作品名称"].apply(clean_title)
        video_people["作品名称"] = video_people["作品名称"].apply(clean_title)

        valid_titles = set(video_people["作品名称"])
        video_df = video_df[video_df["作品名称"].isin(valid_titles)].copy()

        all_titles = set(self.get_daily_video_data()["作品名称"].apply(clean_title))
        unmatched_titles = all_titles - valid_titles
        if unmatched_titles:
            print("⚠️ 以下作品在员工信息中没有匹配上，将被跳过：")
            for t in unmatched_titles:
                print(" -", t)

        if video_df.empty:
            print("❌ 没有匹配到任何有效作品数据，请检查作品标题格式是否一致。")
            return pd.DataFrame(columns=['作品名称', '总分成', '日期'])

        total_money = self.total_money_dy()

        metric_weights = {
            '播放量': 0.05,
            '点赞量': 0.05,
            '收藏量': 0.3,
            '评论量': 0.3,
            '分享量': 0.3
        }

        for metric, weight in metric_weights.items():
            max_val = video_df[metric].max()
            standardized_col = f'{metric}_标准化'
            video_df[standardized_col] = video_df[metric].apply(lambda x: (x / max_val) * weight if max_val > 0 else 0)

        standardized_cols = [f'{metric}_标准化' for metric in metric_weights.keys()]
        video_df['总表现分'] = video_df[standardized_cols].sum(axis=1)
        video_scores = video_df.groupby('作品名称', as_index=False)['总表现分'].sum()
        video_scores = video_scores[video_scores['总表现分'] > 0]

        total_customers = total_money // 50
        total_scores = video_scores['总表现分'].sum()

        video_scores['客户数'] = ((video_scores['总表现分'] / total_scores) * total_customers).round().astype(int)

        discrepancy = total_customers - video_scores['客户数'].sum()
        if discrepancy != 0 and not video_scores.empty:
            idx_max = video_scores['总表现分'].idxmax()
            video_scores.at[idx_max, '客户数'] += discrepancy

        video_scores['总分成'] = video_scores['客户数'] * 50
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        video_scores['日期'] = yesterday_str

        return video_scores[['作品名称', '总分成', '日期']]

    def get_video_people(self):
        appId = "67c280b7c6387c4f4afd50ae"
        entryId = "67c2816ffa795e84a8fe45b9"
        video_people = self.jdy.get_jdy_data(app_id=appId, entry_id=entryId)

        rows = []
        for doc in video_people:
            title_raw = doc.get("_widget_1740646149825", "")
            title_cleaned = title_raw.split('#')[0].rstrip()

            base_fields = {
                "账号名称": doc.get("_widget_1741257105163", ""),
                "账号ID": doc.get("_widget_1741257105165", ""),
                "是否完整内容": doc.get("_widget_1740798082550", ""),
                "正片标题": title_cleaned,
                "提交日期": doc.get("_widget_1740646149826", ""),
                "来源门店/部门": doc.get("_widget_1741934971937", {}).get("name", "")
            }

            user_groups = {
                "完整内容提供": [u.get("username") for u in doc.get("_widget_1740798082567", [])],
                "半成品内容提供": [u.get("username") for u in doc.get("_widget_1740798082568", [])],
                "剪辑": [u.get("username") for u in doc.get("_widget_1740798082569", [])],
                "发布运营": [u.get("username") for u in doc.get("_widget_1740798082570", [])]
            }

            max_len = max(len(g) for g in user_groups.values()) or 1
            aligned_groups = {}
            for field, users in user_groups.items():
                aligned_groups[field] = users + [None] * (max_len - len(users))

            row = {**base_fields, **aligned_groups}
            rows.append(row)

        df = pd.DataFrame(rows)

        exploded_dfs = []
        for group in ["完整内容提供", "半成品内容提供", "剪辑", "发布运营"]:
            temp_df = df[["正片标题"] + [group]].explode(group)
            temp_df = temp_df.rename(columns={group: "人员", "_id": "人员类别"})
            temp_df["人员类别"] = group
            exploded_dfs.append(temp_df)

        final_df = pd.concat(exploded_dfs, ignore_index=True)
        base_df = df[["正片标题", "账号名称", "账号ID", "是否完整内容", "提交日期", "来源门店/部门"]]
        final_df = final_df.merge(base_df, on="正片标题", how="left")
        final_df = final_df.dropna(subset=["人员"])

        column_order = [
            "正片标题", "账号名称", "账号ID", "是否完整内容",
            "人员类别", "人员", "提交日期", "来源门店/部门"
        ]
        return final_df[column_order].reset_index(drop=True)

    def everyone_money(self):
        video_people = self.get_video_people()
        video_money = self.video_dividend()

        video_people = video_people.rename(columns={"正片标题": "作品名称"})
        merged = video_people.merge(video_money, on="作品名称", how="left")
        merged["总分成"] = merged["总分成"].fillna(0)

        total_dividend_before = video_money["总分成"].sum()
        print(f"🔍 合并前 总分成金额: {total_dividend_before}")

        RULES = {
            ("是", "完整内容提供"): 0.6,
            ("是", "发布运营"): 0.4,
            ("否", "半成品内容提供"): 0.4,
            ("否", "剪辑"): 0.2,
            ("否", "发布运营"): 0.4
        }

        merged["分成比例"] = merged.apply(lambda row: RULES.get((row["是否完整内容"], row["人员类别"]), 0.2), axis=1)

        missing_rules = merged[merged["分成比例"].isna()]
        if not missing_rules.empty:
            print("⚠️ 以下数据未匹配到分成规则:")
            print(missing_rules[["作品名称", "人员类别", "是否完整内容"]])

        merged = merged.dropna(subset=["分成比例"])
        merged["人数"] = merged.groupby(["作品名称", "人员类别"])["人员"].transform("count")
        merged["分成金额"] = (merged["总分成"] * merged["分成比例"] / merged["人数"]).round(2)

        result = merged.loc[(merged["人员"].notnull()), ["作品名称", "人员", "分成金额"]]
        result.to_excel('原始分成.xlsx', index=False)

        total_dividend_after = result["分成金额"].sum()
        print(f"✅ 分配后 总分成金额: {total_dividend_after}")

        if round(total_dividend_before, 2) != round(total_dividend_after, 2):
            print(f"⚠️ 警告: 总金额有损失！缺少 {round(total_dividend_before - total_dividend_after, 2)}")

        summary = result.groupby("人员", as_index=False)["分成金额"].sum()
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        summary["日期"] = yesterday_str
        summary = summary[summary["分成金额"] > 0]

        return summary.reset_index(drop=True)

    def upload_to_jdy(self):
        appId = "67c280b7c6387c4f4afd50ae"
        entryId = "67d7097d08e5f607c4cfd028"
        final_data = self.everyone_money()
        asyncio.run(self.jdy.batch_create(app_id=appId, entry_id=entryId, source_data=final_data))


if __name__ == '__main__':
    dividend = Dividend()
    # print(dividend.total_money_dy())
    # print(dividend.get_custom_count()['客资数'].sum())
    # video_people = dividend.get_video_people()
    # video_people.to_excel('视频管理.xlsx', index=False)
    # people_money = dividend.everyone_money()
    # people_money.to_excel('每人分红金额.xlsx', index=False)
    # data = dividend.video_dividend()
    # data.to_excel('视频分红.xlsx', index=False)
    # dividend.upload_to_jdy()
    dividend.upload_dy_custom()
