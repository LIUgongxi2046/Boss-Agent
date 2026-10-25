import json
from urllib.parse import urlencode

from aiohttp import web
from jsonschema import Draft202012Validator, FormatChecker

from business import encode, require
from boss_source_policy import source_validity
from runtime_page_read_tools import _BossPageReadTool


SOP_WORKSPACE_PROJECTIONS=frozenset({
    "notifications","minutes","approvals","outbox","organization","research",
    "people","travel","calendar","memory","decisions","knowledge",
})


class _StrictSopReadTool(_BossPageReadTool):
    def validate_params(self,params):
        validator=Draft202012Validator(self.parameters,format_checker=FormatChecker())
        return ["读取参数不符合正式Schema："+".".join(map(str,error.absolute_path))
                for error in validator.iter_errors(params)]

    def _validate_call(self,params):
        require(not self.validate_params(params),"读取参数不符合正式Schema",web.HTTPBadRequest)


class BossTasksReadTool(_StrictSopReadTool):
    @property
    def name(self):
        return "bossTasksRead"

    @property
    def description(self):
        return "读取本人当前交办、正式状态、反馈、关联消息、本人承诺及来源审阅状态；历史承诺保持独立字段，来源失效不表示任务已经完成。读取不确认完成或发送消息。"

    @property
    def parameters(self):
        return {"type":"object","properties":{},"additionalProperties":False}

    async def execute(self):
        return encode(self._read("/api/boss/ui/tasks"))


class BossCalendarConflictReadTool(_StrictSopReadTool):
    @property
    def name(self):
        return "bossCalendarConflictRead"

    @property
    def description(self):
        return "按照明确开始时间、结束时间及IANA时区读取当前会议的工作时间冲突；会议结束未知时保留检查限制，取消或举行状态保持当前业务语义。该读取不保存私人日历或改变会议。"

    @property
    def parameters(self):
        return {"type":"object","properties":{
            "starts_at":{"type":"string","format":"date-time"},
            "ends_at":{"type":"string","format":"date-time"},
            "timezone":{"type":"string"},
        },"required":["starts_at","ends_at","timezone"],"additionalProperties":False}

    async def execute(self,starts_at,ends_at,timezone):
        params={"starts_at":starts_at,"ends_at":ends_at,"timezone":timezone}
        self._validate_call(params)
        return encode(self._read("/api/boss/ui/calendar-conflict",urlencode(params)))


class BossCalendarSharePreviewTool(_StrictSopReadTool):
    @property
    def name(self):
        return "bossCalendarSharePreview"

    @property
    def description(self):
        return "只读预览本人已经单独授权且当前有效的busy-share内容；仅含占用时间、时区及收件人编号，撤销、过期、删除或换版后拒绝。预览不创建分享、不提供外部访问、不披露私人正文。"

    @property
    def parameters(self):
        return {"type":"object","properties":{"share_id":{
            "type":"string","pattern":"^busy-share-","maxLength":100,
        }},"required":["share_id"],"additionalProperties":False}

    async def execute(self,share_id):
        self._validate_call({"share_id":share_id})
        value=self._read("/api/boss/ui/calendar-share-preview",urlencode({"share_id":share_id}))
        allowed={"source_type","share_id","share_status","recipient_id","fields","busy",
                 "starts_at","ends_at","timezone","external_delivery_created",
                 "preview_only_not_external_access","read_at"}
        require(set(value)<=allowed and value["fields"]==["busy","starts_at","ends_at","timezone"]
                and value["share_id"]==share_id and value["share_status"]=="ACTIVE_SIMULATED"
                and value["busy"] is True and value["external_delivery_created"] is False
                and value["preview_only_not_external_access"] is True,
                "分享预览字段或当前采用状态不符",web.HTTPConflict)
        return encode(value)


class BossWorkspaceReadTool(_StrictSopReadTool):
    def __init__(self,api,role,*,allowed_projections,owner_id="boss-1"):
        super().__init__(api,role,owner_id=owner_id)
        require(isinstance(allowed_projections,(list,tuple,set,frozenset)) and bool(allowed_projections)
                and all(isinstance(item,str) for item in allowed_projections),
                "服务端必须明确本次允许的投影集合",web.HTTPBadRequest)
        allowed=frozenset(allowed_projections)
        require(len(allowed)==len(allowed_projections) and allowed<=SOP_WORKSPACE_PROJECTIONS,
                "服务端投影集合超出当前方法读取范围",web.HTTPForbidden)
        self._allowed_projections=allowed

    @property
    def allowed_projections(self):
        return self._allowed_projections

    @property
    def name(self):
        return "bossWorkspaceRead"

    @property
    def description(self):
        return "读取服务端明确允许的本人工作投影，保留当前状态、历史记录、来源版本与资料缺口；研究未准备保持空结果，记忆仅effective=true可持续采用，历史决定不能充当当前对象。审批附件按当前来源资格报告attachment_status，申请描述保持已提交内容。读取不确认本人决定、不生成授权、不执行任何写入。"

    @property
    def parameters(self):
        return {"type":"object","properties":{"projection":{
            "type":"string","enum":sorted(self.allowed_projections),
        }},"required":["projection"],"additionalProperties":False}

    async def execute(self,projection):
        self._validate_call({"projection":projection})
        value=self._read("/api/boss/ui/workspace/"+projection)
        require(value["projection"]==projection and value["namespace"]==self._api.namespace,
                "读取投影或执行空间不符",web.HTTPConflict)
        if projection=="approvals":
            value=self._current_approval_sources(value)
        return encode(value)

    def _current_approval_sources(self,value):
        # 申请历史保持原样，附件采用状态按当前来源政策重新核查。
        with self._api.store.connect() as db:
            db.execute("BEGIN")
            self._api.store.active(db,self._api.namespace)
            clock=self._api.store.get(db,self._api.namespace,"clock","current")["at"]
            applications=[]
            for item in value["applications"]:
                current=self._api.store.get(db,self._api.namespace,"application",item["application_id"])
                require(all(current[key]==item[key] for key in ("version","source_id","source_version")),
                        "申请版本已经变化，需要重新读取",web.HTTPConflict)
                row=db.execute("SELECT body FROM objects WHERE namespace=? AND kind='document' AND id=?",
                               (self._api.namespace,item["source_id"])).fetchone()
                status="MISSING_OR_CHANGED"
                if row is not None:
                    document=json.loads(row[0])
                    if document.get("source_type")!="SIMULATED" or document.get("access_scope")!=self._owner_id:
                        status="NOT_AUTHORIZED"
                    elif document["version"]==item["source_version"]:
                        state=source_validity(document,clock)
                        status="CURRENT" if state=="VALID" else state
                applications.append({**item,"attachment_status":status})
        return {**value,"applications":applications}
