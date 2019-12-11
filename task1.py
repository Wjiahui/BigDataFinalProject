import sys
import pyspark
import string
import json
from pyspark import SparkContext
from pyspark.sql import SparkSession
from pyspark.sql import SQLContext
from pyspark.sql.functions import isnan, when, count,col,countDistinct,desc
import os
import re
os.environ['PYSPARK_PYTHON'] = '/usr/local/bin/python3.7'

#时间转化为数字,以便对date排序
def convert(x):
    x = str(x)
    reg = re.compile('^\d{2}\/\d{2}\/\d{4}.*$')
    if re.search(reg, x):
        res = int(x[6:10])
        res = res * 13 + int(x[0:2])
        res = res * 32 + int(x[3: 5])
        return res
    else:
        res = int(x[0:4])
        res = res * 13 + int(x[5:7])
        res = res * 32 + int(x[8:10])
        return res



sc = SparkContext()
spark = SparkSession.builder.appName("projectTask1").config("spark.some.config.option", "some-value").getOrCreate()
sqlContext = SQLContext(sparkContext=spark.sparkContext, sparkSession=spark )


#读取datasets的序号和名称（需要dataset.tsv)
df_rf = sqlContext.read.format('com.databricks.spark.csv'). \
    option("sep", "\t"). \
    option("header", False). \
    option("inferSchema", "true"). \
    option("multiline", "true"). \
    load('NYCOpenData/datasets.tsv')

datasets_index = df_rf.rdd.map(lambda x: (x[0], x[1])).collect()
# start_position = int(sys.argv[1])
# end_position = int(sys.argv[2])

#
# for idx in range(start_position, end_position):
id_list = []
for i in sys.argv[1:]:
    id_list.append(int(i))
for idx in id_list:
    try:
        print("processing the" + str(idx) + "th dataset:" + str(datasets_index[idx][0]))
        df = sqlContext.read.format('com.databricks.spark.csv'). \
            option("sep", "\t"). \
            option("header", True). \
            option("inferSchema", "true"). \
            option("multiline", "true"). \
            load('NYCOpenData/' + str(datasets_index[idx][0]) + '.tsv.gz')

        # df.printSchema()
        #提取dataname
        datasets_name = datasets_index[idx][1]

        column_specification = []
        key_column_candidates = []
        output_json = {
            "dataset_name": datasets_name,
            "columns": df.columns,
            "column_specification": column_specification,
            "key_column_candidates": key_column_candidates
        }

        # the number of row
        num_df = df.count()

        for column in df.columns:

            df_col = df.select("`"+column+"`")
            df_null = df_col.filter(df_col["`"+column+"`"].isNull())
            df_notnull = df_col.filter(df_col["`"+column+"`"].isNotNull())

            # 计算number_non_empty_cell,number_empty_cell,number_distinct_values
            number_non_empty_cells = df_notnull.count()
            number_empty_cells = df_null.count()

            rdd_notnull = df_notnull.rdd

            number_distinct_values = rdd_notnull.distinct().count()
            number_frequency_values = rdd_notnull.map(lambda x: (x[0], 1)).reduceByKey(lambda x, y: x + y) \
                .sortBy(lambda x: x[1], ascending=False).map(lambda x: x[0]).take(5)
            # number_distinct_values = df.agg((countDistinct(col(column)).alias(column))).rdd.map(lambda x: x[0]).collect()[0]
            # df_frequency = df.filter(df[column].isNotNull())
            # number_frequency_values = df_frequency.select(column).rdd.map(lambda x: (x[0], 1)).reduceByKey(lambda x, y: x + y)\
            #    .sortBy(lambda x: x[1], ascending=False).map(lambda x: x[0]).take(5)

            data_types = []


            # INTEGER
            df_integer = df_col.filter(df_col["`"+column+"`"].rlike('^\d+$'))  # 用正则表达式匹配整数
            count_integer = df_integer.count()
            # 如果存在integer type，filter去掉非integer的部分，计算
            if count_integer > 0:
                rdd_integer = df_integer.rdd.map(lambda x: int(x[0]))
                type_tag = {
                    "type": "INTEGER(LONG)",
                    "count": count_integer,
                    "max_value": rdd_integer.max(),
                    "min-value": rdd_integer.min(),
                    "mean": rdd_integer.mean(),
                    "stddev": rdd_integer.stdev()
                }
                data_types.append(type_tag)

            # REAL
            df_real = df_col.filter(df_col["`"+column+"`"].rlike('^\d+\.[0-9]+$'))
            count_real = df_real.count()
            if count_real > 0:
                rdd_real = df_real.rdd.map(lambda x: float(x[0]))
                type_tag = {
                    "type": "REAL",
                    "count": count_real,
                    "max_value": rdd_real.max(),
                    "min-value": rdd_real.min(),
                    "mean": rdd_real.mean(),
                    "stddev": rdd_real.stdev()
                }
                data_types.append(type_tag)

            # DATE
            df_date = df_col.filter(df_col["`"+column+"`"].rlike('^\d{2}\/\d{2}\/\d{4}.*$') | df_col["`"+column+"`"].rlike('^\d{4}\-\d{2}\-\d{2}.*$'))
            count_date = df_date.count()
            if count_date > 0:
                rdd_date = df_date.rdd.map(lambda x: x[0])
                max_value = rdd_date.map(lambda x: (x, convert(x))).sortBy(lambda x: x[1], ascending=False).map(lambda x: str(x[0])).take(1)[0]  #错误1，json无datetime格式，要str()
                min_value = rdd_date.map(lambda x: (x, convert(x))).sortBy(lambda x: x[1], ascending=True).map(lambda x: str(x[0])).take(1)[0]
                type_tag = {
                    "type": "DATE/TIME",
                    "count": count_date,
                    "max_value": max_value,
                    "min-value": min_value
                }

                for key in range(len(number_frequency_values)):
                    number_frequency_values[key] = str(number_frequency_values[key])  # 错误1
                #print("date exists!!!!!!!!!!!!!!!!!!!!")

                data_types.append(type_tag)

            # TEXT
            count_null = number_empty_cells
            count_text = num_df - (count_integer + count_real + count_date + count_null)
            if count_text > 0:
                df_text = df_col.filter(~ (df_col["`"+column+"`"].rlike('^\d{2}\/\d{2}\/\d{4}.*$') \
                                           | df_col["`"+column+"`"].rlike('^\d+\.[0-9]+$') | df_col["`"+column+"`"].rlike('^\d+$')))
                rdd_text = df_text.rdd.distinct()
                longest = rdd_text.sortBy(lambda x: len(str(x)), ascending=False).map(lambda x: str(x[0])).take(5)
                shortest = rdd_text.sortBy(lambda x: len(str(x)), ascending=True).map(lambda x: str(x[0])).take(5)
                avglen = rdd_text.map(lambda x: len(str(x[0])))
                avglen = avglen.mean()

                type_tag = {
                    "type": "TEXT",
                    "count": count_text,
                    "short_values": shortest,
                    "longest_value": longest,
                    "average_length": avglen
                }
                data_types.append(type_tag)

                #for key in range(len(number_frequency_values)):
                    #number_frequency_values[key] = str(number_frequency_values[key])  # 错误1


            col_json = {
                    "column_name": column,
                    "number_non_empty_cells": number_non_empty_cells,
                    "number_empty_cells": number_empty_cells,
                    "number_distinct_values": number_distinct_values,
                    "frequent_values": number_frequency_values,
                    "data_types": data_types
            }  # 每列的json输出


            # 添加每个列的json output
            column_specification.append(col_json)

            # df[col]无null值 无重复 等于总行数
            if (number_empty_cells == 0 and number_distinct_values == num_df):
                key_column_candidates.append(column)

        # 写入json文件
        json_str = json.dumps(output_json)
        with open("output_for_json/index-" + str(idx) + "-" + str(datasets_index[idx][0]) + '.json', 'w') as json_file:
            json_file.write(json_str)
    except Exception:
        print("exception")
        with open("output_for_json/exception.txt", 'a') as f:
            f.write(str(idx) + "-" + str(datasets_index[idx][0])+"\n")
        pass
    continue



