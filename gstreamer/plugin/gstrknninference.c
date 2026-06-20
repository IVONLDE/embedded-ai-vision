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
#include <math.h>

/* RKNN API */
#include "rknn_api.h"

/* OpenCV (用于图像预处理) */
#include <opencv2/opencv.hpp>

GST_DEBUG_CATEGORY_STATIC(rknn_inference_debug);
#define GST_CAT_DEFAULT rknn_inference_debug

/* ── 自定义 GstMeta: 检测结果 ─────────────────────────────── */
/*
 * RknnDetectionMeta — 附加到 GstBuffer 的检测结果元数据
 *
 * 由 rknninference 元素在每帧推理后附加到 outgoing buffer,
 * 下游元素 (rknndraw, appsink 等) 通过 gst_buffer_get_meta() 读取。
 */
typedef struct _RknnDetectionMeta
{
    GstMeta parent;

    gint num_detections;
    /* 检测框数组 (在 meta 之后分配) */
    gfloat *boxes;       /* [num_detections * 6]: x1,y1,x2,y2,conf,class_id */
    gchar  **class_names; /* [num_detections]: 类别名称 */
} RknnDetectionMeta;

GType rknn_detection_meta_api_get_type(void);
#define RKNN_DETECTION_META_API_TYPE (rknn_detection_meta_api_get_type())
#define RKNN_DETECTION_META_INFO (rknn_detection_meta_get_info())
static const GstMetaInfo *rknn_detection_meta_get_info(void);

/* GstMeta 注册 */
GType rknn_detection_meta_api_get_type(void)
{
    static GType type = 0;
    if (g_once_init_enter(&type)) {
        static const gchar *tags[] = { NULL };
        GType _type = gst_meta_api_type_register(
            "RknnDetectionMetaAPI", tags);
        g_once_init_leave(&type, _type);
    }
    return type;
}

static gboolean rknn_detection_meta_init(GstMeta *meta,
                                          gpointer params,
                                          GstBuffer *buffer)
{
    RknnDetectionMeta *rmeta = (RknnDetectionMeta *)meta;
    rmeta->num_detections = 0;
    rmeta->boxes = NULL;
    rmeta->class_names = NULL;
    return TRUE;
}

static void rknn_detection_meta_free(GstMeta *meta, GstBuffer *buffer)
{
    RknnDetectionMeta *rmeta = (RknnDetectionMeta *)meta;
    if (rmeta->boxes) {
        g_free(rmeta->boxes);
        rmeta->boxes = NULL;
    }
    if (rmeta->class_names) {
        for (gint i = 0; i < rmeta->num_detections; i++)
            g_free(rmeta->class_names[i]);
        g_free(rmeta->class_names);
        rmeta->class_names = NULL;
    }
    rmeta->num_detections = 0;
}

static const GstMetaInfo *rknn_detection_meta_get_info(void)
{
    static const GstMetaInfo *info = NULL;
    if (g_once_init_enter(&info)) {
        static const GstMetaInfo rknn_meta_info = {
            RKNN_DETECTION_META_API_TYPE,
            "RknnDetectionMeta",
            sizeof(RknnDetectionMeta),
            rknn_detection_meta_init,
            rknn_detection_meta_free,
            NULL  /* no transform_func — 检测结果在 transform 时重新生成 */
        };
        g_once_init_leave(&info, &rknn_meta_info);
    }
    return info;
}

/*
 * 便捷宏: 从 GstBuffer 获取检测结果
 * 用法:
 *   RknnDetectionMeta *meta = RKNN_GET_DETECTION_META(buffer);
 *   if (meta) {
 *       for (int i = 0; i < meta->num_detections; i++) { ... }
 *   }
 */
#define RKNN_GET_DETECTION_META(buf) \
    ((RknnDetectionMeta *)gst_buffer_get_meta((buf), RKNN_DETECTION_META_API_TYPE))

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

    /* Anchor 定义 (YOLOv5) */
    gfloat anchors[3][6];

    /* 性能统计 */
    gdouble avg_inference_ms;

    /* 输入 buffer (预分配, 避免每帧 malloc) */
    guchar *prealloc_input;
} GstRknnInference;

typedef struct _GstRknnInferenceClass
{
    GstVideoFilterClass parent_class;
} GstRknnInferenceClass;

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

/* ── sigmoid ───────────────────────────────────────────── */
static inline gfloat sigmoid_f(gfloat x)
{
    return 1.0f / (1.0f + expf(-x));
}

/* ── IoU 计算 ──────────────────────────────────────────── */
static gfloat calc_iou(gfloat xmin0, gfloat ymin0, gfloat xmax0, gfloat ymax0,
                        gfloat xmin1, gfloat ymin1, gfloat xmax1, gfloat ymax1)
{
    gfloat w = fmaxf(0.0f, fminf(xmax0, xmax1) - fmaxf(xmin0, xmin1));
    gfloat h = fmaxf(0.0f, fminf(ymax0, ymax1) - fmaxf(ymin0, ymin1));
    gfloat i = w * h;
    gfloat u = (xmax0 - xmin0) * (ymax0 - ymin0) +
               (xmax1 - xmin1) * (ymax1 - ymin1) - i;
    return (u <= 0.0f) ? 0.0f : (i / u);
}

/* ── 快速排序 (按置信度降序) ───────────────────────────── */
static void quick_sort_desc(gfloat *scores, gint *indices,
                             gint left, gint right)
{
    if (left >= right) return;
    gint i = left, j = right;
    gfloat pivot = scores[indices[(left + right) / 2]];
    while (i <= j) {
        while (scores[indices[i]] > pivot) i++;
        while (scores[indices[j]] < pivot) j--;
        if (i <= j) {
            gint tmp = indices[i];
            indices[i] = indices[j];
            indices[j] = tmp;
            i++; j--;
        }
    }
    if (left < j) quick_sort_desc(scores, indices, left, j);
    if (i < right) quick_sort_desc(scores, indices, i, right);
}

/* ── NMS ──────────────────────────────────────────────── */
static void run_nms(GArray *boxes, gfloat *scores, gint *indices,
                    gint valid_count, gfloat nms_threshold)
{
    for (gint i = 0; i < valid_count; i++) {
        if (indices[i] == -1) continue;
        gint n = indices[i];
        gfloat *box_n = &g_array_index(boxes, gfloat, n * 4);
        for (gint j = i + 1; j < valid_count; j++) {
            if (indices[j] == -1) continue;
            gint m = indices[j];
            gfloat *box_m = &g_array_index(boxes, gfloat, m * 4);
            gfloat iou = calc_iou(
                box_n[0], box_n[1], box_n[0] + box_n[2],
                box_n[1] + box_n[3],
                box_m[0], box_m[1], box_m[0] + box_m[2],
                box_m[1] + box_m[3]);
            if (iou > nms_threshold)
                indices[j] = -1;
        }
    }
}

/* ── 标签加载 ─────────────────────────────────────────── */
static gboolean load_labels(GstRknnInference *self)
{
    if (!self->labels_path)
        return TRUE;

    FILE *fp = fopen(self->labels_path, "r");
    if (!fp) {
        GST_WARNING_OBJECT(self, "Cannot open labels file: %s",
                           self->labels_path);
        return FALSE;
    }

    gint count = 0;
    gchar line[256];
    while (fgets(line, sizeof(line), fp))
        count++;
    rewind(fp);

    self->num_classes = count;
    self->labels = g_new0(gchar *, count);

    gint i = 0;
    while (fgets(line, sizeof(line), fp) && i < count) {
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
    if (model_len != (gint)fread(model_data, 1, model_len, fp)) {
        GST_ERROR_OBJECT(self, "Failed to read model file");
        fclose(fp);
        g_free(model_data);
        return FALSE;
    }
    fclose(fp);

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

    /* 预分配输入 buffer */
    self->prealloc_input = (guchar *)g_malloc(
        self->model_width * self->model_height * self->model_channels);

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
static gboolean preprocess_frame(GstRknnInference *self,
                                 GstVideoFrame *frame)
{
    GstVideoInfo *info = &frame->info;
    gint width = GST_VIDEO_INFO_WIDTH(info);
    gint height = GST_VIDEO_INFO_HEIGHT(info);
    gint stride = GST_VIDEO_INFO_PLANE_STRIDE(info, 0);

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

    cv::resize(rgb, resized, cv::Size(new_w, new_h));

    gint top = (self->model_height - new_h) / 2;
    gint bottom = self->model_height - new_h - top;
    gint left = (self->model_width - new_w) / 2;
    gint right = self->model_width - new_w - left;

    cv::copyMakeBorder(resized, padded, top, bottom, left, right,
                       cv::BORDER_CONSTANT, cv::Scalar(114, 114, 114));

    /* 拷贝到预分配 buffer */
    memcpy(self->prealloc_input, padded.data,
           self->model_width * self->model_height * self->model_channels);

    return TRUE;
}

/*
 * ── 单层 YOLOv5 解码 ─────────────────────────────────────
 *
 * 从 YOLOv5 原始输出解码边界框 (完整的 sigmoid + anchor 映射)。
 * 与 edge/src/inference/yolov5/decode.cpp 中的 process_layer_fp 逻辑一致。
 */
static gint decode_yolov5_layer(gfloat *input, const gfloat *anchor,
                                 gint grid_h, gint grid_w, gint stride,
                                 gint num_classes,
                                 gfloat threshold,
                                 GArray *boxes, GArray *scores,
                                 GArray *class_ids)
{
    gint valid_count = 0;
    gint grid_len = grid_h * grid_w;
    gint props = 5 + num_classes;

    /*
     * 将置信度阈值转换为 sigmoid 的逆:
     *  若 sigmoid(x) > threshold, 则 x > -ln(1/threshold - 1)
     */
    gfloat thres_sigmoid_inv = (threshold > 0.0f)
        ? -1.0f * logf((1.0f / threshold) - 1.0f)
        : -1e10f;

    for (gint a = 0; a < 3; a++) {
        for (gint i = 0; i < grid_h; i++) {
            for (gint j = 0; j < grid_w; j++) {
                /* objectness (在 sigmoid 之前的 logit 空间中比较) */
                gfloat box_conf = input[(props * a + 4) * grid_len + i * grid_w + j];
                if (box_conf < thres_sigmoid_inv)
                    continue;

                gint offset = (props * a) * grid_len + i * grid_w + j;
                gfloat *in_ptr = input + offset;

                /* sigmoid 解码 + anchor 映射 */
                gfloat bx = sigmoid_f(in_ptr[0]) * 2.0f - 0.5f;
                gfloat by = sigmoid_f(in_ptr[1 * grid_len]) * 2.0f - 0.5f;
                gfloat bw = sigmoid_f(in_ptr[2 * grid_len]) * 2.0f;
                gfloat bh = sigmoid_f(in_ptr[3 * grid_len]) * 2.0f;

                bx = (bx + j) * stride;
                by = (by + i) * stride;
                bw = bw * bw * anchor[a * 2];
                bh = bh * bh * anchor[a * 2 + 1];
                bx -= bw / 2.0f;
                by -= bh / 2.0f;

                /* 添加 bbox [x, y, w, h] */
                gfloat box[4] = { bx, by, bw, bh };
                g_array_append_vals(boxes, box, 4);

                /* 最大类别概率 */
                gfloat max_class_prob = in_ptr[5 * grid_len];
                gfloat conf = sigmoid_f(box_conf);
                gfloat score = conf * sigmoid_f(max_class_prob);

                /* 找到最佳类别 (对于多类模型) */
                gint best_class = 0;
                if (num_classes > 1) {
                    gfloat best_prob = max_class_prob;
                    for (gint c = 1; c < num_classes; c++) {
                        gfloat class_prob = in_ptr[(5 + c) * grid_len];
                        if (class_prob > best_prob) {
                            best_prob = class_prob;
                            best_class = c;
                        }
                    }
                    score = conf * sigmoid_f(best_prob);
                }

                gfloat s = score;
                g_array_append_val(scores, s);
                gint cid = best_class;
                g_array_append_val(class_ids, cid);
                valid_count++;
            }
        }
    }
    return valid_count;
}

/* ── 完整 YOLOv5 后处理 ────────────────────────────────── */
/*
 * postprocess_yolov5_full — 完整的 YOLOv5 解码 + NMS
 *
 * 直接复用了 edge/src/inference/yolov5/decode.cpp 中的算法,
 * 包括:
 *   - COCO anchors (3 层 × 3 组 = 18 个 anchor)
 *   - sigmoid 激活的 box 坐标解码
 *   - 置信度阈值过滤
 *   - NMS (IoU 阈值过滤)
 *
 * 输出: GArray of {x1,y1,x2,y2,conf,class_id,class_name}
 */
static GArray *postprocess_yolov5_full(GstRknnInference *self,
                                        gfloat *outputs[3],
                                        gint orig_w, gint orig_h)
{
    /*
     * Layer 配置:
     *   Layer 0: stride=8,  grid=80×80  (小目标)
     *   Layer 1: stride=16, grid=40×40  (中目标)
     *   Layer 2: stride=32, grid=20×20  (大目标)
     */
    static const gint strides[3] = {8, 16, 32};
    static const gint grids[3][2] = {{80, 80}, {40, 40}, {20, 20}};

    GArray *boxes   = g_array_new(FALSE, FALSE, sizeof(gfloat));   /* [x,y,w,h] */
    GArray *scores  = g_array_new(FALSE, FALSE, sizeof(gfloat));
    GArray *class_ids = g_array_new(FALSE, FALSE, sizeof(gint));

    /* 三层解码 */
    for (gint layer = 0; layer < 3; layer++) {
        decode_yolov5_layer(
            outputs[layer],
            self->anchors[layer],
            grids[layer][0], grids[layer][1],
            strides[layer],
            self->num_classes > 0 ? self->num_classes : 1,
            self->threshold,
            boxes, scores, class_ids);
    }

    gint valid_count = boxes->len / 4;
    if (valid_count <= 0) {
        g_array_free(boxes, TRUE);
        g_array_free(scores, TRUE);
        g_array_free(class_ids, TRUE);
        return NULL;
    }

    /* 按置信度降序排列 */
    GArray *indices = g_array_new(FALSE, FALSE, sizeof(gint));
    g_array_set_size(indices, valid_count);
    for (gint i = 0; i < valid_count; i++)
        g_array_index(indices, gint, i) = i;

    quick_sort_desc((gfloat *)scores->data,
                    (gint *)indices->data, 0, valid_count - 1);

    /* NMS */
    run_nms(boxes, (gfloat *)scores->data,
            (gint *)indices->data, valid_count, self->nms_threshold);

    /* 构建最终结果 */
    GArray *results = g_array_new(FALSE, TRUE,
        sizeof(gfloat) * 6 + sizeof(gchar *));  /* 不使用混合 struct, 分拆存储 */

    /* 改用固定 struct */
    typedef struct {
        gfloat x1, y1, x2, y2;
        gfloat confidence;
        gint class_id;
        gchar class_name[64];
    } DetectionBox;

    GArray *detections = g_array_new(FALSE, TRUE, sizeof(DetectionBox));

    for (gint i = 0; i < valid_count; i++) {
        if (g_array_index(indices, gint, i) == -1)
            continue;
        gint n = g_array_index(indices, gint, i);
        gfloat score = g_array_index(scores, gfloat, n);
        if (score < self->threshold)
            continue;

        gfloat *b = &g_array_index(boxes, gfloat, n * 4);
        DetectionBox det;
        det.x1 = b[0];
        det.y1 = b[1];
        det.x2 = b[0] + b[2];
        det.y2 = b[1] + b[3];
        det.confidence = score;
        det.class_id = g_array_index(class_ids, gint, n);

        /* 类别名称 */
        if (self->labels && det.class_id < self->num_classes) {
            g_strlcpy(det.class_name, self->labels[det.class_id],
                      sizeof(det.class_name));
        } else {
            g_snprintf(det.class_name, sizeof(det.class_name),
                       "class_%d", det.class_id);
        }

        g_array_append_val(detections, det);
    }

    g_array_free(boxes, TRUE);
    g_array_free(scores, TRUE);
    g_array_free(class_ids, TRUE);
    g_array_free(indices, TRUE);
    g_array_free(results, TRUE);

    return detections;
}

/* ── GstVideoFilter 核心: transform_frame_ip ───────────── */
static GstFlowReturn
gst_rknn_inference_transform_frame_ip(GstVideoFilter *filter,
                                      GstVideoFrame *frame)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(filter);
    gint ret;

    self->frame_count++;

    /* 隔帧检测 */
    if (self->interval > 1 &&
        self->frame_count % self->interval != 0) {
        return GST_FLOW_OK;
    }

    /* ── 预处理 ── */
    preprocess_frame(self, frame);

    gint input_size = self->model_width * self->model_height *
                      self->model_channels;

    memset(self->inputs, 0, sizeof(self->inputs));
    self->inputs[0].index = 0;
    self->inputs[0].type = RKNN_TENSOR_UINT8;
    self->inputs[0].size = input_size;
    self->inputs[0].fmt = RKNN_TENSOR_NHWC;
    self->inputs[0].buf = self->prealloc_input;

    ret = rknn_inputs_set(self->ctx, 1, self->inputs);
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_inputs_set failed! ret=%d", ret);
        return GST_FLOW_ERROR;
    }

    /* ── NPU 推理 ── */
    ret = rknn_run(self->ctx, NULL);
    if (ret < 0) {
        GST_ERROR_OBJECT(self, "rknn_run failed! ret=%d", ret);
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
        return GST_FLOW_ERROR;
    }

    /* ── 后处理 (完整的 YOLOv5 decode + NMS) ── */
    gfloat *output_buffs[3];
    for (gint i = 0; i < 3; i++)
        output_buffs[i] = (gfloat *)self->outputs[i].buf;

    GstVideoInfo *info = &frame->info;
    gint orig_w = GST_VIDEO_INFO_WIDTH(info);
    gint orig_h = GST_VIDEO_INFO_HEIGHT(info);

    GArray *detections = postprocess_yolov5_full(self, output_buffs,
                                                   orig_w, orig_h);

    /* ── 附加检测结果到 GstBuffer (GstMeta) ── */
    if (detections && detections->len > 0) {
        GstBuffer *buffer = gst_video_frame_get_buffer(frame);
        if (buffer) {
            RknnDetectionMeta *meta = (RknnDetectionMeta *)
                gst_buffer_add_meta(buffer, RKNN_DETECTION_META_INFO, NULL);

            if (meta) {
                meta->num_detections = detections->len;
                meta->boxes = g_new0(gfloat, detections->len * 6);
                meta->class_names = g_new0(gchar *, detections->len);

                typedef struct {
                    gfloat x1, y1, x2, y2;
                    gfloat confidence;
                    gint class_id;
                    gchar class_name[64];
                } DetectionBox;

                for (guint i = 0; i < detections->len; i++) {
                    DetectionBox *det = &g_array_index(detections,
                                                       DetectionBox, i);
                    meta->boxes[i * 6 + 0] = det->x1;
                    meta->boxes[i * 6 + 1] = det->y1;
                    meta->boxes[i * 6 + 2] = det->x2;
                    meta->boxes[i * 6 + 3] = det->y2;
                    meta->boxes[i * 6 + 4] = det->confidence;
                    meta->boxes[i * 6 + 5] = (gfloat)det->class_id;
                    meta->class_names[i] = g_strdup(det->class_name);
                }
            }
        }
    }

    if (detections)
        g_array_free(detections, TRUE);

    /* ── 释放 RKNN 输出 ── */
    rknn_outputs_release(self->ctx, 3, self->outputs);

    if (self->frame_count % 100 == 0) {
        GST_INFO_OBJECT(self, "Frame %d processed", self->frame_count);
    }

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

    if (self->ctx)
        rknn_destroy(self->ctx);

    g_free(self->model_path);
    g_free(self->labels_path);

    if (self->labels) {
        for (gint i = 0; i < self->num_classes; i++)
            g_free(self->labels[i]);
        g_free(self->labels);
    }

    g_free(self->prealloc_input);

    G_OBJECT_CLASS(gst_rknn_inference_parent_class)->finalize(object);
}

static gboolean gst_rknn_inference_start(GstBaseTransform *trans)
{
    GstRknnInference *self = GST_RKNN_INFERENCE(trans);

    if (!self->model_path) {
        GST_ERROR_OBJECT(self, "model property is required");
        return FALSE;
    }

    /* 初始化 YOLOv5 COCO anchors */
    static const gfloat default_anchors[3][6] = {
        {10.0f, 13.0f, 16.0f, 30.0f, 33.0f, 23.0f},
        {30.0f, 61.0f, 62.0f, 45.0f, 59.0f, 119.0f},
        {116.0f, 90.0f, 156.0f, 198.0f, 373.0f, 326.0f}
    };
    memcpy(self->anchors, default_anchors, sizeof(default_anchors));

    /* 加载标签 */
    load_labels(self);

    /* 加载 RKNN 模型 */
    if (!load_rknn_model(self))
        return FALSE;

    self->frame_count = 0;

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

    gst_element_class_set_static_metadata(
        element_class,
        "RKNN NPU Inference",
        "Video/Filter/AI",
        "Run YOLOv5 object detection on Rockchip NPU via RKNN API",
        "Edge AI Vision Project");

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
    self->threshold = 0.3f;
    self->nms_threshold = 0.45f;
    self->interval = 1;
    self->ctx = 0;
    self->frame_count = 0;
    self->labels = NULL;
    self->num_classes = 0;
    self->avg_inference_ms = 0.0;
    self->prealloc_input = NULL;
}

/* ── 插件注册 ──────────────────────────────────────────── */
static gboolean plugin_init(GstPlugin *plugin)
{
    GST_DEBUG_CATEGORY_INIT(rknn_inference_debug,
                            "rknninference", 0,
                            "RKNN NPU Inference Element");

    /* 注册自定义 GstMeta 类型 */
    gst_meta_register(RKNN_DETECTION_META_API_TYPE,
                      "RknnDetectionMeta",
                      sizeof(RknnDetectionMeta),
                      rknn_detection_meta_init,
                      rknn_detection_meta_free,
                      NULL);

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