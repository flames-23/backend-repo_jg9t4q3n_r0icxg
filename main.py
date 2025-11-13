import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="E-Procurement API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Utilities ----------

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


def with_id(doc):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    return doc


# ---------- Models for requests ----------

class UserIn(BaseModel):
    name: str
    email: str
    role: str  # employee | manager | purchasing
    department: Optional[str] = None
    manager_id: Optional[str] = None


class SupplierIn(BaseModel):
    name: str
    code: str
    contact_email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class ItemIn(BaseModel):
    sku: str
    name: str
    uom: str
    description: Optional[str] = None
    category: Optional[str] = None


class PRLineIn(BaseModel):
    sku: str
    name: str
    qty: float
    uom: str


class PRCreate(BaseModel):
    employee_id: str
    manager_id: str
    reason: Optional[str] = None
    lines: List[PRLineIn]


class PRDecision(BaseModel):
    manager_id: str
    approve: bool
    rejected_reason: Optional[str] = None


class POCreate(BaseModel):
    pr_id: str
    supplier_id: str


class GRLineIn(BaseModel):
    sku: str
    name: str
    qty_received: float
    uom: str


class GRCreate(BaseModel):
    po_id: str
    lines: List[GRLineIn]


# ---------- Health ----------

@app.get("/")
def read_root():
    return {"message": "E-Procurement Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------- Users ----------

@app.post("/users")
def create_user(user: UserIn):
    user_doc = user.model_dump()
    user_doc["is_active"] = True
    new_id = create_document("user", user_doc)
    return {"id": new_id}


@app.get("/users")
def list_users(role: Optional[str] = Query(default=None)):
    q = {"is_active": True}
    if role:
        q["role"] = role
    users = db["user"].find(q).limit(100)
    return [with_id(u) for u in users]


# ---------- Master data: Items, Suppliers, Inventory ----------

@app.post("/suppliers")
def create_supplier(s: SupplierIn):
    new_id = create_document("supplier", s.model_dump())
    return {"id": new_id}


@app.get("/suppliers")
def list_suppliers():
    return [with_id(s) for s in db["supplier"].find({}).limit(100)]


@app.post("/items")
def create_item(item: ItemIn):
    # Also initialize inventory record if not exists
    item_id = create_document("item", item.model_dump())
    inv = db["inventory"].find_one({"sku": item.sku})
    if not inv:
        create_document("inventory", {"sku": item.sku, "on_hand": 0, "uom": item.uom})
    return {"id": item_id}


@app.get("/items")
def list_items():
    return [with_id(i) for i in db["item"].find({}).limit(200)]


@app.get("/inventory")
def get_inventory():
    return [with_id(i) for i in db["inventory"].find({}).limit(500)]


# ---------- Purchase Requests (PR) ----------

@app.post("/prs")
def create_pr(pr: PRCreate):
    # Validate users
    emp = db["user"].find_one({"_id": oid(pr.employee_id), "role": "employee"})
    if not emp:
        raise HTTPException(400, detail="Invalid employee_id")
    mgr = db["user"].find_one({"_id": oid(pr.manager_id), "role": "manager"})
    if not mgr:
        raise HTTPException(400, detail="Invalid manager_id")
    pr_doc = {
        "employee_id": pr.employee_id,
        "manager_id": pr.manager_id,
        "reason": pr.reason,
        "lines": [l.model_dump() for l in pr.lines],
        "status": "submitted",
    }
    pr_id = create_document("purchaserequest", pr_doc)
    # Notify manager
    create_document(
        "notification",
        {
            "to_user_id": pr.manager_id,
            "role": None,
            "title": "New Purchase Request",
            "message": f"PR {pr_id} awaiting your approval",
            "link_type": "PR",
            "link_id": pr_id,
            "read": False,
        },
    )
    return {"id": pr_id}


@app.get("/prs")
def list_prs(status: Optional[str] = None, manager_id: Optional[str] = None, employee_id: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    if manager_id:
        q["manager_id"] = manager_id
    if employee_id:
        q["employee_id"] = employee_id
    cursor = db["purchaserequest"].find(q).sort("created_at", -1)
    return [with_id(d) for d in cursor]


@app.post("/prs/{pr_id}/decision")
def decide_pr(pr_id: str, decision: PRDecision):
    pr_doc = db["purchaserequest"].find_one({"_id": oid(pr_id)})
    if not pr_doc:
        raise HTTPException(404, detail="PR not found")
    if pr_doc.get("manager_id") != decision.manager_id:
        raise HTTPException(403, detail="Manager not assigned to this PR")
    if pr_doc.get("status") not in ["submitted"]:
        raise HTTPException(400, detail="PR is not pending approval")

    if decision.approve:
        db["purchaserequest"].update_one(
            {"_id": oid(pr_id)},
            {"$set": {"status": "approved", "approved_by": decision.manager_id, "approved_at": datetime.now(timezone.utc)}},
        )
        # Notify purchasing role
        create_document(
            "notification",
            {
                "to_user_id": None,
                "role": "purchasing",
                "title": "PR Approved",
                "message": f"PR {pr_id} is ready for PO",
                "link_type": "PR",
                "link_id": pr_id,
                "read": False,
            },
        )
    else:
        db["purchaserequest"].update_one(
            {"_id": oid(pr_id)},
            {"$set": {"status": "rejected", "rejected_reason": decision.rejected_reason or ""}},
        )
        # Notify employee
        create_document(
            "notification",
            {
                "to_user_id": pr_doc.get("employee_id"),
                "role": None,
                "title": "PR Rejected",
                "message": f"PR {pr_id} was rejected",
                "link_type": "PR",
                "link_id": pr_id,
                "read": False,
            },
        )
    return {"ok": True}


# ---------- Purchase Orders (PO) ----------

@app.post("/pos")
def create_po(data: POCreate):
    pr_doc = db["purchaserequest"].find_one({"_id": oid(data.pr_id)})
    if not pr_doc:
        raise HTTPException(404, detail="PR not found")
    if pr_doc.get("status") != "approved":
        raise HTTPException(400, detail="PR is not approved")
    supplier = db["supplier"].find_one({"_id": oid(data.supplier_id)})
    if not supplier:
        raise HTTPException(400, detail="Invalid supplier_id")

    po_doc = {
        "pr_id": data.pr_id,
        "supplier_id": data.supplier_id,
        "lines": [
            {"sku": l["sku"], "name": l["name"], "qty": l["qty"], "uom": l["uom"]}
            for l in pr_doc.get("lines", [])
        ],
        "status": "sent",
    }
    po_id = create_document("purchaseorder", po_doc)
    db["purchaserequest"].update_one({"_id": oid(data.pr_id)}, {"$set": {"status": "ordered", "po_id": po_id}})

    # Notify employee that PO has been created
    create_document(
        "notification",
        {
            "to_user_id": pr_doc.get("employee_id"),
            "role": None,
            "title": "PO Created",
            "message": f"PO {po_id} created from your PR",
            "link_type": "PO",
            "link_id": po_id,
            "read": False,
        },
    )
    return {"id": po_id}


@app.get("/pos")
def list_pos(status: Optional[str] = None):
    q = {}
    if status:
        q["status"] = status
    return [with_id(p) for p in db["purchaseorder"].find(q).sort("created_at", -1)]


# ---------- Goods Receipt (GR) and Inventory Update ----------

@app.post("/grs")
def create_gr(data: GRCreate):
    po = db["purchaseorder"].find_one({"_id": oid(data.po_id)})
    if not po:
        raise HTTPException(404, detail="PO not found")

    # Create GR document
    gr_doc = {"po_id": data.po_id, "lines": [l.model_dump() for l in data.lines]}
    gr_id = create_document("goodsreceipt", gr_doc)

    # Update inventory for each line (upsert on sku)
    for line in data.lines:
        db["inventory"].update_one(
            {"sku": line.sku},
            {"$inc": {"on_hand": float(line.qty_received)}, "$setOnInsert": {"uom": line.uom}},
            upsert=True,
        )

    # Update PO status
    total_po_qty = sum(float(l.get("qty", 0)) for l in po.get("lines", []))
    total_received = 0.0
    grs = db["goodsreceipt"].find({"po_id": data.po_id})
    for g in grs:
        for l in g.get("lines", []):
            total_received += float(l.get("qty_received", 0))
    new_status = "received" if total_received >= total_po_qty else "partially_received"
    db["purchaseorder"].update_one({"_id": oid(data.po_id)}, {"$set": {"status": new_status}})

    # Notify employee that goods were received
    # Find PR to get employee_id
    pr = db["purchaserequest"].find_one({"_id": oid(po.get("pr_id"))})
    if pr:
        create_document(
            "notification",
            {
                "to_user_id": pr.get("employee_id"),
                "role": None,
                "title": "Goods Received",
                "message": f"GR {gr_id} recorded and inventory updated",
                "link_type": "GR",
                "link_id": gr_id,
                "read": False,
            },
        )

    return {"id": gr_id}


@app.get("/grs")
def list_grs():
    return [with_id(g) for g in db["goodsreceipt"].find({}).sort("created_at", -1)]


# ---------- Notifications ----------

@app.get("/notifications")
def list_notifications(user_id: Optional[str] = None, role: Optional[str] = None):
    q = {"read": False}
    if user_id:
        q["to_user_id"] = user_id
    if role:
        q["role"] = role
    return [with_id(n) for n in db["notification"].find(q).sort("created_at", -1)]


@app.post("/notifications/{notif_id}/read")
def mark_notification_read(notif_id: str):
    db["notification"].update_one({"_id": oid(notif_id)}, {"$set": {"read": True, "updated_at": datetime.now(timezone.utc)}})
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
