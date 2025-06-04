import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import datetime

# Models from buyer_concierge to construct the initial RFQ
from buyer_concierge.models import SubmitRFQ as BuyerSubmitRFQ, BomItem as BuyerBomItem, Currency as BuyerCurrency

# Models from supplier_quoter to validate the quote structure received
from supplier_quoter.models import Quote as SupplierQuoteResponse, Currency as SupplierCurrency

# Catalog from supplier_quoter to determine expected quote values
from supplier_quoter.catalog import PRODUCT_CATALOG, DEFAULT_UNKNOWN_ITEM_PRICE, DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS

# DB models from shared to query the database
from shared.models_db import RFQTable, QuoteTable, RFQStatus


@pytest.mark.asyncio
async def test_successful_rfq_to_quote_flow(http_client: httpx.AsyncClient, db_session: AsyncSession):
    """
    Tests the full flow:
    1. Test client sends an RFQ to Buyer Concierge's /a2a endpoint.
    2. Buyer Concierge calls Supplier Quoter.
    3. Supplier Quoter returns a quote based on its catalog.
    4. Buyer Concierge stores RFQ and Quote, and returns quote details.
    5. Test verifies the returned quote and database state.
    """
    # Prepare RFQ payload using known items from supplier's catalog
    part_number_1 = "PN-001"  # Exists in catalog
    qty_1 = 2
    part_number_2 = "PN-UNKNOWN-FOR-INTEGRATION-TEST" # Does not exist
    qty_2 = 3

    rfq_payload = BuyerSubmitRFQ(
        bom=[
            BuyerBomItem(partNumber=part_number_1, qty=qty_1, spec="Integration test spec 1"),
            BuyerBomItem(partNumber=part_number_2, qty=qty_2, spec="Integration test spec 2")
        ],
        currency=BuyerCurrency.USD,
        deadline=datetime.date.today() + datetime.timedelta(days=30)
    )

    # Make the request to Buyer Concierge's /a2a endpoint
    # This endpoint itself is an A2A endpoint, so we send the RFQ payload directly.
    # A dummy token is used, assuming buyer_concierge is configured for TEST_AUTH_BYPASS or accepts it.
    headers = {"Authorization": "Bearer test-token"}
    
    response = await http_client.post("/a2a", json=rfq_payload.model_dump(mode='json'), headers=headers)

    # Print response for debugging if needed
    print(f"Buyer Concierge Response Status: {response.status_code}")
    print(f"Buyer Concierge Response JSON: {response.json()}")

    assert response.status_code == 200
    response_data = response.json()

    assert response_data["status"] == "success"
    assert "rfq_id" in response_data
    assert "client_rfq_id" in response_data # This is the RFQTable.client_rfq_id
    assert "quote" in response_data

    # --- Verify the quote details returned in the HTTP response ---
    # This quote is what supplier_quoter generated and buyer_concierge passed through
    returned_quote_data = response_data["quote"]
    
    # Validate structure by parsing with SupplierQuoteResponse (optional, but good for robustness)
    parsed_supplier_quote = SupplierQuoteResponse(**returned_quote_data)

    assert parsed_supplier_quote.supplierId == "SupplierQuoter_OnlineMartInc-v1" # From supplier_quoter/main.py
    assert parsed_supplier_quote.currency == SupplierCurrency.USD # Matches RFQ currency
    assert len(parsed_supplier_quote.items) == 2

    # Item 1 (PN-001) - Known item
    item1_catalog_details = PRODUCT_CATALOG[part_number_1]
    assert parsed_supplier_quote.items[0].partNumber == part_number_1
    assert parsed_supplier_quote.items[0].quantity == qty_1
    assert parsed_supplier_quote.items[0].unitPrice == item1_catalog_details["unit_price"]
    assert parsed_supplier_quote.items[0].leadTimeDays == item1_catalog_details["lead_time_days"]

    # Item 2 (PN-UNKNOWN-FOR-INTEGRATION-TEST) - Unknown item
    assert parsed_supplier_quote.items[1].partNumber == part_number_2
    assert parsed_supplier_quote.items[1].quantity == qty_2
    assert parsed_supplier_quote.items[1].unitPrice == DEFAULT_UNKNOWN_ITEM_PRICE
    assert parsed_supplier_quote.items[1].leadTimeDays == DEFAULT_UNKNOWN_ITEM_LEAD_TIME_DAYS
    
    expected_total_price = round(
        (item1_catalog_details["unit_price"] * qty_1) + (DEFAULT_UNKNOWN_ITEM_PRICE * qty_2), 2
    )
    assert parsed_supplier_quote.totalPrice == expected_total_price
    assert parsed_supplier_quote.validUntil == datetime.date.today() + datetime.timedelta(days=7)


    # --- Verify database state in Buyer Concierge ---
    rfq_db_id = response_data["rfq_id"]

    # Fetch RFQ from DB
    stmt_rfq = select(RFQTable).where(RFQTable.id == rfq_db_id)
    result_rfq = await db_session.execute(stmt_rfq)
    db_rfq_entry = result_rfq.scalar_one_or_none()

    assert db_rfq_entry is not None
    assert db_rfq_entry.status == RFQStatus.QUOTED
    assert db_rfq_entry.currency.value == rfq_payload.currency.value # Compare Enum value

    # Fetch Quote from DB
    stmt_quote = select(QuoteTable).where(QuoteTable.rfq_table_id == rfq_db_id)
    result_quote = await db_session.execute(stmt_quote)
    db_quote_entry = result_quote.scalar_one_or_none()

    assert db_quote_entry is not None
    # Compare DB quote with the parsed_supplier_quote from the response
    assert db_quote_entry.supplier_id == parsed_supplier_quote.supplierId
    assert db_quote_entry.total_price == parsed_supplier_quote.totalPrice
    assert db_quote_entry.currency.value == parsed_supplier_quote.currency.value # Compare Enum value
    assert db_quote_entry.valid_until == parsed_supplier_quote.validUntil
    
    # Verify quote items in DB (QuoteTable.quoted_items is JSONB)
    # db_quote_entry.quoted_items should be a list of dicts matching parsed_supplier_quote.items
    assert len(db_quote_entry.quoted_items) == len(parsed_supplier_quote.items)
    for i, db_item in enumerate(db_quote_entry.quoted_items):
        expected_item = parsed_supplier_quote.items[i]
        assert db_item["partNumber"] == expected_item.partNumber
        assert db_item["quantity"] == expected_item.quantity
        assert db_item["unitPrice"] == expected_item.unitPrice
        assert db_item["leadTimeDays"] == expected_item.leadTimeDays
        
    # Verify the client_rfq_id generated by RFQService
    generated_client_rfq_id_from_response = response_data["client_rfq_id"]
    assert isinstance(generated_client_rfq_id_from_response, str)
    assert len(generated_client_rfq_id_from_response) == 32 # UUID4().hex is 32 chars
    assert db_rfq_entry.client_rfq_id == generated_client_rfq_id_from_response 