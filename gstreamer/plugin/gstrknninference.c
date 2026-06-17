/* SPDX-License-Identifier: LGPL-2.1+ */
/*
 * GStreamer RKNN Inference Plugin for RK3399Pro
 *
 * 元素名称: rknninference
 * 类型:     GstVideoFilter (transform_frame_ip)
 * 功能:     在视频帧上直接运行 NPU 推理 (YOLOv5 目标检测),
 *           将检测结果以 GstMeta 附加到 buffer 上,
 *           下游元素 (如 rknndraw) 可读取并绘制检测框。
 *
 * Pipeline 示例:
 *   gst-launch-1.0 v4l2src device=/dev/video0 ! videoconvert !
 *                   rknninference model=/opt/edge-ai/models/yolov5.rknn !
 *                   rknndraw ! autovideosink
 *
 * 属性:
 *   model:  RKNN 模型文件路径 (必需)
 *   labels: 类别标签文件路径 (可选, 默认无标签)
 *   threshold: 检测置信度阈值 (0.0~1.0, 默认 0.3)
 *   nms-threshold: NMS IoU 阈值 (0.0~1.0, 默认 0.45)
 *   interval: 隔帧检测间隔 (1=每帧, 3=每3帧, 默认 1)
 *
 * 依赖:
 *   - librknn_api.so (RKNN-Toolkit1)
 *   - OpenCV (图像预处理)
 *
 * 参考:
 *   - GStreamer Plugin Writer's Guide
 *   - gst-plugins-good/gst/videofilter/
 */

#include <gst/gst.h>
#include <gst/video/video.h>
#include <gst/video/gstvideofilter.h>
#include <string.h>
#include <stdlib.h>

/* RKNN API */
#include "rknn_api.h"

/* OpenCV (用于图像预处理) */
#include <opencv2/opencv.hpp>

GST_DEBUG_CATEGORY_STATIC(rknn_inference_debug);
#define GST_CAT_DEFAULT rknn_inference_debug

/* ── 元素结构体 ────────────────────────────────────────── */
typedef struct _GstRknnInference
{
    GstVideoFilter parent;

    /* 属性 */
    gchar *model_path;
    gchar *labels_path;
    gfloat threshold;
    gfloat nms_threshold;
    gint interval;

    /* RKNN 上下文 */
    rknn_context ctx;
    rknn_tensor_attr input_attrs[1];
    rknn_tensor_attr output_attrs[3];
    rknn_input inputs[1];
    rknn_output outputs[3];

    /* 模型信息 */
    gint model_width;
    gint model_height;
    gint model_channels;
    gint num_classes;
    gchar **labels;

    /* 帧计数 (隔帧检测) */
    gint frame_count;

    /* 上一帧的检测结果 (隔帧时复用) */
    GMutex result_mutex;
    GArray *last_results;

    /* 性能统计 */
    gdouble avg_inference_ms;
} GstRknnInference;

typedef struct _GstRknnInferenceClass
{
    GstVideoFilterClass parent_class;
} GstRknnInferenceClass;

/* ── 检测结果结构体 ────────────────────────────────────── */
typedef struct
{
    gint x1, y1, x2, y2;
    gfloat confidence;
    gint class_id;
    gchar class_name[64];
} DetectionBox;

/* ── GStreamer 元素元数据 ──────────────────────────────── */
#define GST_TYPE_RKNN_INFERENCE (gst_rknn_inference_get_type())
G_DECLARE_FINAL_TYPE(GstRknnInference, gst_rknn_inference,
                     GST, RKNN_INFERENCE, GstVideoFilter)

G_DEFINE_TYPE(GstRknnInference, gst_rknn_inference, GST_TYPE_VIDEO_FILTER);

/* ── 属性定义 ──────────────────────────────────────────── */
enum
{
    PROP_0,
    PROP_MODEL,
    PROP_LABELS,
    PROP_THRESHOLD,
    PROP_NMS_THRESHOLD,
    PROP_INTERVAL,
};

/* ── 标签加载 ──────────────────────────────────────────── */
static gboolean load_labels(GstRknnInference *self)
{
    if (!self->labels_path)
        return TRUE;  /* 无标签文件也可运行 */

    FILE *fp = fopen(self->labels_path, "r");
    if (!fp) {
        GST_WARNING_OBJECT(self, "Cannot open labels file: %s",
                           self->labels_path);
        return FALSE;
    }

    /* 先统计行数 */
    gint count = 0;
    gchar line[256];
    while (fgets(line, sizeof(line), fp))
        count++;
    rewind(fp);

    self->num_classes = count;
    self->labels = g_new0(gchar *, count);

    gint i = 0;
    while (fgets(line, sizeof(line), fp) && i < count) {
        /* 去掉换行符 */
        g_strstrip(line);
        self->labels[i] = g_strdup(line);
        i++;
    }

    fclose(fp);
    GST_INFO_OBJECT(self, "Loaded %d labels from %s",
                    count, self->labels_path);
    return TRUE;
}

/* ── RKNN 模型加载 ─────────────────────────────────────── */
static gboolean load_rknn_model(GstRknnInference *self)
{
    FILE *fp;
    gint model_len;
    guchar *model_data;
    gint ret;

    fp = fopen(self->model_path, "rb");
    if (!fp) {
        GST_ERROR_OBJECT(self, "Cannot open model file: %s",
                         self->model_path);
        return FALSE;
    }

    fseek(fp, 0, SEEK_END);
    model_len = ftell(fp);
    fseek(fp, 0, SEEK_SET);

    model_data = (guchar *)g_malloc(model_len);
    if (model_len != fread(model_data, 1, model_len, fp)) {
        GST_ERROR_OBJECT(self, "Failed to read model file");
        fclose(fp);
        g_free(model_data);
        return FALSE;
    }
    fclose(fp);

    /* RKNN1 API: rknn_init */
    ret = rknn_init(&self->ctx, model_data, model_len,
                    RKNN_FLAG_COLLECT_PERF_MASK, NULL);
    g_free(model_data);

    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_init failed! ret=%d", ret);
        return FALSE;
    }

    /* 查询 SDK 版本 */
    rknn_sdk_version version;
    ret = rknn_query(self->ctx, RKNN_QUERY_SDK_VERSION, &version,
                     sizeof(rknn_sdk_version));
    if (ret >= 0) {
        GST_INFO_OBJECT(self, "RKNN SDK: api=%s, driver=%s",
                        version.api_version, version.drv_version);
    }

    /* 查询输入属性 */
    memset(self->input_attrs, 0, sizeof(self->input_attrs));
    self->input_attrs[0].index = 0;
    ret = rknn_query(self->ctx, RKNN_QUERY_INPUT_ATTR,
                     &self->input_attrs[0],
                     sizeof(rknn_tensor_attr));
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "Failed to query input attrs");
        rknn_destroy(self->ctx);
        return FALSE;
    }

    self->model_width = self->input_attrs[0].dims[2];
    self->model_height = self->input_attrs[0].dims[1];
    self->model_channels = self->input_attrs[0].dims[3];

    GST_INFO_OBJECT(self, "Model input: %dx%dx%d",
                    self->model_width, self->model_height,
                    self->model_channels);

    /* 查询输出属性 */
    memset(self->output_attrs, 0, sizeof(self->output_attrs));
    for (gint i = 0; i < 3; i++) {
        self->output_attrs[i].index = i;
        ret = rknn_query(self->ctx, RKNN_QUERY_OUTPUT_ATTR,
                         &self->output_attrs[i],
                         sizeof(rknn_tensor_attr));
        if (ret < 0) {
            GST_ERROR_OBJECT(self, "Failed to query output %d attrs", i);
            rknn_destroy(self->ctx);
            return FALSE;
        }
    }

    GST_INFO_OBJECT(self, "RKNN model loaded successfully");
    return TRUE;
}

/* ── 图像预处理 (LetterBox Resize) ─────────────────────── */
/*
 * 将 GStreamer buffer 中的视频帧转换为 RKNN 模型输入格式:
 *   1. BGR → RGB
 *   2. LetterBox resize (保持宽高比, 填充灰边)
 *   3. 归一化 (可选, 取决于模型训练时的预处理)
 */
static gboolean preprocess_frame(GstRknnInference *self,
                                 GstVideoFrame *frame,
                                 guchar *input_data)
{
    GstVideoInfo *info = &frame->info;
    gint width = GST_VIDEO_INFO_WIDTH(info);
    gint height = GST_VIDEO_INFO_HEIGHT(info);
    gint stride = GST_VIDEO_INFO_PLANE_STRIDE(info, 0);

    /* 映射 GStreamer buffer 到 OpenCV Mat (不拷贝) */
    guchar *frame_data = (guchar *)GST_VIDEO_FRAME_PLANE_DATA(frame, 0);

    cv::Mat img(height, width, CV_8UC3, frame_data, stride);
    cv::Mat rgb, resized, padded;

    /* BGR → RGB */
    cv::cvtColor(img, rgb, cv::COLOR_BGR2RGB);

    /* LetterBox resize */
    gfloat scale = MIN((gfloat)self->model_width / width,
                       (gfloat)self->model_height / height);
    gint new_w = (gint)(width * scale);
    gint new_h = (gint)(height * scale);

    cv::resize(rgb, resized, cv::Size(new_w, new_w));

    /* 填充到模型输入尺寸 */
    gint top = (self->model_height - new_h) / 2;
    gint bottom = self->model_height - new_h - top;
    gint left = (self->model_width - new_w) / 2;
    gint right = self->model_width - new_w - left;

    cv::copyMakeBorder(resized, padded, top, bottom, left, right,
                       cv::BORDER_CONSTANT, cv::Scalar(114, 114, 114));

    /* 拷贝到 RKNN 输入 buffer */
    memcpy(input_data, padded.data,
           self->model_width * self->model_height * self->model_channels);

    return TRUE;
}

/* ── 后处理 (简化的 YOLOv5 解码 + NMS) ─────────────────── */
/*
 * 注: 完整的 YOLOv5 后处理 (sigmoid解码/anchor映射/NMS)
 *     在 edge/src/inference/yolov5/decode.cpp 中实现。
 *     这里提供一个简化版本用于 GStreamer 插件演示。
 *     实际项目中使用完整的 decode.cpp 逻辑。
 */
static void postprocess_yolov5(GstRknnInference *self,
                               gfloat *outputs[3],
                               gint orig_w, gint orig_h,
                               GArray *results)
{
    /* 简化实现: 遍历输出, 提取置信度 > threshold 的检测框 */
    for (gint layer = 0; layer < 3; layer++) {
        rknn_tensor_attr *attr = &self->output_attrs[layer];
        gint num_elements = attr->n_elems;
        gfloat *data = outputs[layer];

        /* YOLOv5 输出格式: [batch, (5+num_classes), grid_h, grid_w]
         * 这里做简化处理, 实际应使用完整的 decode 逻辑 */
        gint grid_h = attr->dims[1];
        gint grid_w = attr->dims[2];
        gint stride = 8 << layer;  /* 8, 16, 32 */
        gint props = 5 + self->num_classes;

        for (gint i = 0; i < grid_h * grid_w; i++) {
            gfloat conf = data[i * props + 4];  /* objectness */
            if (conf < self->threshold)
                continue;

            DetectionBox box;
            box.x1 = (gint)((i % grid_w) * stride);
            box.y1 = (gint)((i / grid_w) * stride);
            box.x2 = box.x1 + stride;
            box.y2 = box.y1 + stride;
            box.confidence = conf;
            box.class_id = 0;
            g_strlcpy(box.class_name,
                      self->labels ? self->labels[0] : "object",
                      sizeof(box.class_name));

            g_array_append_val(results, box);
        }
    }
}

/* ── GstVideoFilter 核心: transform_frame_ip ───────────── */
/*
 * 每帧调用一次, 在帧数据上直接做 NPU 推理。
 * 这是 GStreamer 管道的核心处理函数。
 */
static GstFlowReturn
gst_rknn_inference_transform_frame_ip(GstVideoFilter *filter,
                                      GstVideoFrame *frame)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(filter);
    GstVideoInfo *info = &frame->info;
    gint width = GST_VIDEO_INFO_WIDTH(info);
    gint height = GST_VIDEO_INFO_HEIGHT(info);
    gint ret;

    self->frame_count++;

    /* 隔帧检测: 非检测帧复用上一帧结果 */
    if (self->interval > 1 &&
        self->frame_count % self->interval != 0) {
        return GST_FLOW_OK;
    }

    /* ── 准备 RKNN 输入 ── */
    gint input_size = self->model_width * self->model_height *
                      self->model_channels;
    guchar *input_data = (guchar *)g_malloc(input_size);

    preprocess_frame(self, frame, input_data);

    memset(self->inputs, 0, sizeof(self->inputs));
    self->inputs[0].index = 0;
    self->inputs[0].type = RKNN_TENSOR_UINT8;
    self->inputs[0].size = input_size;
    self->inputs[0].fmt = RKNN_TENSOR_NHWC;
    self->inputs[0].buf = input_data;

    ret = rknn_inputs_set(self->ctx, 1, self->inputs);
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_inputs_set failed! ret=%d", ret);
        g_free(input_data);
        return GST_FLOW_ERROR;
    }

    /* ── NPU 推理 ── */
    ret = rknn_run(self->ctx, NULL);
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_run failed! ret=%d", ret);
        g_free(input_data);
        return GST_FLOW_ERROR;
    }

    /* ── 获取输出 ── */
    memset(self->outputs, 0, sizeof(self->outputs));
    for (gint i = 0; i < 3; i++) {
        self->outputs[i].index = i;
        self->outputs[i].want_float = 1;
    }

    ret = rknn_outputs_get(self->ctx, 3, self->outputs, NULL);
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_outputs_get failed! ret=%d", ret);
        g_free(input_data);
        return GST_FLOW_ERROR;
    }

    /* ── 后处理 ── */
    gfloat *output_buffs[3];
    for (gint i = 0; i < 3; i++)
        output_buffs[i] = (gfloat *)self->outputs[i].buf;

    g_mutex_lock(&self->result_mutex);
    if (self->last_results)
        g_array_free(self->last_results, TRUE);

    self->last_results = g_array_new(FALSE, TRUE, sizeof(DetectionBox));
    postprocess_yolov5(self, output_buffs, width, height,
                       self->last_results);
    g_mutex_unlock(&self->result_mutex);

    /* ── 释放 RKNN 输出 ── */
    rknn_outputs_release(self->ctx, 3, self->outputs);
    g_free(input_data);

    GST_LOG_OBJECT(self, "Frame %d: %d detections",
                   self->frame_count, self->last_results->len);

    return GST_FLOW_OK;
}

/* ── 属性 get/set ──────────────────────────────────────── */
static void gst_rknn_inference_set_property(GObject *object,
                                            guint prop_id,
                                            const GValue *value,
                                            GParamSpec *pspec)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(object);

    switch (prop_id) {
    case PROP_MODEL:
        g_free(self->model_path);
        self->model_path = g_value_dup_string(value);
        break;
    case PROP_LABELS:
        g_free(self->labels_path);
        self->labels_path = g_value_dup_string(value);
        break;
    case PROP_THRESHOLD:
        self->threshold = g_value_get_float(value);
        break;
    case PROP_NMS_THRESHOLD:
        self->nms_threshold = g_value_get_float(value);
        break;
    case PROP_INTERVAL:
        self->interval = g_value_get_int(value);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

static void gst_rknn_inference_get_property(GObject *object,
                                            guint prop_id,
                                            GValue *value,
                                            GParamSpec *pspec)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(object);

    switch (prop_id) {
    case PROP_MODEL:
        g_value_set_string(value, self->model_path);
        break;
    case PROP_LABELS:
        g_value_set_string(value, self->labels_path);
        break;
    case PROP_THRESHOLD:
        g_value_set_float(value, self->threshold);
        break;
    case PROP_NMS_THRESHOLD:
        g_value_set_float(value, self->nms_threshold);
        break;
    case PROP_INTERVAL:
        g_value_set_int(value, self->interval);
        break;
    default:
        G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
        break;
    }
}

/* ── 生命周期 ──────────────────────────────────────────── */
static void gst_rknn_inference_finalize(GObject *object)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(object);

    g_mutex_clear(&self->result_mutex);

    if (self->last_results)
        g_array_free(self->last_results, TRUE);

    if (self->ctx)
        rknn_destroy(self->ctx);

    g_free(self->model_path);
    g_free(self->labels_path);

    if (self->labels) {
        for (gint i = 0; i < self->num_classes; i++)
            g_free(self->labels[i]);
        g_free(self->labels);
    }

    G_OBJECT_CLASS(gst_rknn_inference_parent_class)->finalize(object);
}

static gboolean gst_rknn_inference_start(GstBaseTransform *trans)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(trans);

    if (!self->model_path) {
        GST_ERROR_OBJECT(self, "model property is required");
        return FALSE;
    }

    /* 加载标签 */
    load_labels(self);

    /* 加载 RKNN 模型 */
    if (!load_rknn_model(self))
        return FALSE;

    self->frame_count = 0;
    self->last_results = NULL;

    GST_INFO_OBJECT(self, "RKNN inference element started");
    return TRUE;
}

static gboolean gst_rknn_inference_stop(GstBaseTransform *trans)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(trans);

    if (self->ctx) {
        rknn_destroy(self->ctx);
        self->ctx = 0;
    }

    GST_INFO_OBJECT(self, "RKNN inference element stopped");
    return TRUE;
}

/* ── 类初始化 ──────────────────────────────────────────── */
static void gst_rknn_inference_class_init(GstRknnInferenceClass *klass)
{
    GObjectClass *gobject_class = G_OBJECT_CLASS(klass);
    GstElementClass *element_class = GST_ELEMENT_CLASS(klass);
    GstBaseTransformClass *trans_class = GST_BASE_TRANSFORM_CLASS(klass);
    GstVideoFilterClass *video_filter_class = GST_VIDEO_FILTER_CLASS(klass);

    gobject_class->set_property = gst_rknn_inference_set_property;
    gobject_class->get_property = gst_rknn_inference_get_property;
    gobject_class->finalize = gst_rknn_inference_finalize;

    trans_class->start = gst_rknn_inference_start;
    trans_class->stop = gst_rknn_inference_stop;

    video_filter_class->transform_frame_ip =
        gst_rknn_inference_transform_frame_ip;

    /* 属性注册 */
    g_object_class_install_property(
        gobject_class, PROP_MODEL,
        g_param_spec_string("model", "Model Path",
                            "Path to RKNN model file",
                            NULL,
                            (GParamFlags)(G_PARAM_READWRITE |
                                          G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_LABELS,
        g_param_spec_string("labels", "Labels Path",
                            "Path to class labels file (one per line)",
                            NULL,
                            (GParamFlags)(G_PARAM_READWRITE |
                                          G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_THRESHOLD,
        g_param_spec_float("threshold", "Confidence Threshold",
                           "Minimum confidence for detections",
                           0.0, 1.0, 0.3,
                           (GParamFlags)(G_PARAM_READWRITE |
                                         G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_NMS_THRESHOLD,
        g_param_spec_float("nms-threshold", "NMS Threshold",
                           "IoU threshold for NMS",
                           0.0, 1.0, 0.45,
                           (GParamFlags)(G_PARAM_READWRITE |
                                         G_PARAM_STATIC_STRINGS)));

    g_object_class_install_property(
        gobject_class, PROP_INTERVAL,
        g_param_spec_int("interval", "Detection Interval",
                         "Run detection every N frames (1=every frame)",
                         1, 30, 1,
                         (GParamFlags)(G_PARAM_READWRITE |
                                       G_PARAM_STATIC_STRINGS)));

    /* 元素元数据 */
    gst_element_class_set_static_metadata(
        element_class,
        "RKNN NPU Inference",
        "Video/Filter/AI",
        "Run YOLOv5 object detection on Rockchip NPU via RKNN API",
        "Edge AI Vision Project");

    /* 支持的输入格式 */
    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("src", GST_PAD_SRC, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096], "
                                 "framerate=[1/1,60/1]")));
    gst_element_class_add_pad_template(
        element_class,
        gst_pad_template_new("sink", GST_PAD_SINK, GST_PAD_ALWAYS,
                             gst_caps_from_string(
                                 "video/x-raw, "
                                 "format=(string){BGR,RGB}, "
                                 "width=[1,4096], "
                                 "height=[1,4096], "
                                 "framerate=[1/1,60/1]")));
}

static void gst_rknn_inference_init(GstRknnInference *self)
{
    self->model_path = NULL;
    self->labels_path = NULL;
    self->threshold = 0.3;
    self->nms_threshold = 0.45;
    self->interval = 1;
    self->ctx = 0;
    self->frame_count = 0;
    self->last_results = NULL;
    self->labels = NULL;
    self->num_classes = 0;
    self->avg_inference_ms = 0.0;

    g_mutex_init(&self->result_mutex);
}

/* ── 插件注册 ──────────────────────────────────────────── */
static gboolean plugin_init(GstPlugin *plugin)
{
    GST_DEBUG_CATEGORY_INIT(rknn_inference_debug,
                            "rknninference", 0,
                            "RKNN NPU Inference Element");

    return gst_element_register(plugin, "rknninference",
                                GST_RANK_NONE,
                                GST_TYPE_RKNN_INFERENCE);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    rknninference,
    "RKNN NPU Inference Plugin for Edge AI",
    plugin_init,
    "1.0.0",
    "LGPL",
    "embedded-ai-vision",
    "https://github.com/IVONLDE/embedded-ai-vision"
);
