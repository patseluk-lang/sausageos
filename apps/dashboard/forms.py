from django import forms

from apps.catalog.models import Material, Supplier
from apps.inventory.models import Warehouse


class ReceiveForm(forms.Form):
    """Goods receipt into a warehouse."""

    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.all(), label="Warehouse")
    material = forms.ModelChoiceField(
        queryset=Material.objects.filter(is_active=True), label="Material"
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_active=True), label="Supplier", required=False
    )
    lot_code = forms.CharField(label="Internal lot code", max_length=64)
    supplier_batch_code = forms.CharField(
        label="Supplier batch code", max_length=64, required=False
    )
    document = forms.CharField(label="Goods receipt note", max_length=64, required=False)
    quantity = forms.DecimalField(label="Quantity", max_digits=12, decimal_places=3, min_value=0)
    unit_cost = forms.DecimalField(label="Unit cost, UAH", max_digits=12, decimal_places=4)
    received_at = forms.DateField(
        label="Received on", widget=forms.DateInput(attrs={"type": "date"})
    )
    expiry_date = forms.DateField(
        label="Expires on", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def clean_lot_code(self):
        from apps.inventory.models import StockLot

        code = self.cleaned_data["lot_code"]
        if StockLot.objects.filter(lot_code=code).exists():
            raise forms.ValidationError("A lot with this code already exists.")
        return code


class StockTakeForm(forms.Form):
    """Stock take for a single lot."""

    counted_quantity = forms.DecimalField(
        label="Counted", max_digits=12, decimal_places=3, min_value=0
    )


class WriteOffForm(forms.Form):
    """Write-off from a lot."""

    quantity = forms.DecimalField(label="Quantity", max_digits=12, decimal_places=3, min_value=0)
    reason = forms.CharField(label="Reason", max_length=255)
