"""
Database Schemas for E-Procurement System

Each Pydantic model maps to a MongoDB collection using the lowercase class name as the collection name.

Collections:
- user: employees, managers, purchasing staff
- supplier: supplier master
- item: item master (SKU-level definitions)
- inventory: current on-hand stock by SKU
- purchaserequest: PR documents created by employees
- purchaseorder: PO documents created by purchasing
- goodsreceipt: GR documents recorded on delivery
- notification: simple notification documents for role-based inboxes
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Work email")
    role: str = Field(..., description="Role: employee | manager | purchasing")
    department: Optional[str] = Field(None, description="Department name")
    manager_id: Optional[str] = Field(None, description="Manager user id for employees")
    is_active: bool = Field(True, description="Whether user is active")

class Supplier(BaseModel):
    name: str = Field(..., description="Supplier name")
    code: str = Field(..., description="Unique supplier code")
    contact_email: Optional[str] = Field(None, description="Supplier contact email")
    phone: Optional[str] = Field(None, description="Supplier phone")
    address: Optional[str] = Field(None, description="Supplier address")

class Item(BaseModel):
    sku: str = Field(..., description="Unique SKU")
    name: str = Field(..., description="Item name")
    uom: str = Field(..., description="Unit of measure (e.g., pcs, box)")
    description: Optional[str] = Field(None, description="Item description")
    category: Optional[str] = Field(None, description="Category")

class Inventory(BaseModel):
    sku: str = Field(..., description="SKU")
    on_hand: float = Field(0, ge=0, description="On-hand quantity")
    uom: str = Field(..., description="Unit of measure")

class PRLine(BaseModel):
    sku: str = Field(..., description="SKU requested")
    name: str = Field(..., description="Item name snapshot")
    qty: float = Field(..., gt=0, description="Requested quantity")
    uom: str = Field(..., description="Unit of measure")

class PurchaseRequest(BaseModel):
    employee_id: str = Field(..., description="Employee who created")
    manager_id: str = Field(..., description="Approver manager user id")
    lines: List[PRLine] = Field(..., description="Requested items")
    status: str = Field("submitted", description="submitted | approved | rejected | ordered")
    reason: Optional[str] = Field(None, description="Business justification")
    approved_by: Optional[str] = Field(None, description="Manager who approved")
    approved_at: Optional[datetime] = Field(None, description="Approval timestamp")
    rejected_reason: Optional[str] = Field(None, description="Rejection reason")
    po_id: Optional[str] = Field(None, description="Linked PO id if converted")

class POLine(BaseModel):
    sku: str
    name: str
    qty: float
    uom: str

class PurchaseOrder(BaseModel):
    pr_id: str = Field(..., description="Source PR id")
    supplier_id: str = Field(..., description="Supplier id")
    lines: List[POLine]
    status: str = Field("sent", description="draft | sent | received | partially_received")

class GRLine(BaseModel):
    sku: str
    name: str
    qty_received: float = Field(..., gt=0)
    uom: str

class GoodsReceipt(BaseModel):
    po_id: str
    lines: List[GRLine]

class Notification(BaseModel):
    to_user_id: Optional[str] = Field(None, description="Recipient user id (optional)")
    role: Optional[str] = Field(None, description="Recipient role if broadcast by role")
    title: str
    message: str
    link_type: Optional[str] = Field(None, description="Related entity type: PR | PO | GR")
    link_id: Optional[str] = Field(None, description="Related entity id")
    read: bool = Field(False)
