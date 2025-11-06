# db_repository.py
import sys
import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
from typing import List, Dict, Any, Optional

# DynamoDB constants
DYNAMO_TABLE_NAME = "TournamentTable"
CONFIG_SK = "CONFIG"


class DynamoRepository:
    """
    Handles all direct communication with the DynamoDB table for one tournament.
    The PK (partition key) is unique per tournament: "TOURNAMENT#<tournament_id>"
    """

    def __init__(self, table_name: str, pk_value: str):
        self.pk = pk_value
        self.db = boto3.resource("dynamodb")
        self.table = self.db.Table(table_name)

    def get_config(self) -> Dict[str, Any]:
        """Fetches the CONFIG item for the current tournament."""
        try:
            result = self.table.get_item(Key={"PK": self.pk, "SK": CONFIG_SK})
            return result.get("Item", {})
        except Exception as e:
            print(f"Error fetching config: {e}", file=sys.stderr)
            return {}

    def update_config(self, update_expr: str, expr_values: Dict[str, Any]) -> bool:
        """Updates the CONFIG item for the current tournament."""
        try:
            self.table.update_item(
                Key={"PK": self.pk, "SK": CONFIG_SK},
                UpdateExpression=update_expr,
                ExpressionAttributeValues=expr_values,
            )
            return True
        except Exception as e:
            print(f"Error updating config: {e}", file=sys.stderr)
            return False


    def _get_items_by_type(self, item_type: str) -> List[Dict[str, Any]]:
        """
        Fetches items of a specific type (PLAYER#, MATCH#, etc.)
        for the current tournament.
        """
        try:
            response = self.table.query(
                KeyConditionExpression=Key("PK").eq(self.pk)
                & Key("SK").begins_with(f"{item_type}#")
            )
            return response.get("Items", [])
        except Exception as e:
            print(f"Error querying {item_type} items: {e}", file=sys.stderr)
            return []

    # Domain-Specific Fetchers

    def get_players(self) -> List[Dict[str, Any]]:
        """Returns all players for this tournament."""
        return self._get_items_by_type("PLAYER")

    def get_matches(self) -> List[Dict[str, Any]]:
        """Returns all matches for this tournament."""
        return self._get_items_by_type("MATCH")

    def get_match(self, match_id: str) -> Optional[Dict[str, Any]]:
        """Fetches one match by ID."""
        try:
            result = self.table.get_item(
                Key={"PK": self.pk, "SK": f"MATCH#{match_id}"}
            )
            return result.get("Item")
        except Exception as e:
            print(f"Error getting match {match_id}: {e}", file=sys.stderr)
            return None

    # Write Operations

    def put_item(self, item: Dict[str, Any]) -> bool:
        """Inserts or replaces an item (player, match, or config)."""
        try:
            self.table.put_item(Item=item)
            return True
        except Exception as e:
            print(f"Error putting item: {e}", file=sys.stderr)
            return False

    def update_item(
        self,
        key: Dict[str, Any],
        update_expression: str,
        expression_names: Optional[Dict[str, str]] = None,
        expression_values: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Generic update method."""
        try:
            params = {
                "Key": key,
                "UpdateExpression": update_expression,
            }
            if expression_names:
                params["ExpressionAttributeNames"] = expression_names
            if expression_values:
                params["ExpressionAttributeValues"] = expression_values
            self.table.update_item(**params)
            return True
        except Exception as e:
            print(f"Error updating item: {e}", file=sys.stderr)
            return False

    def delete_item(self, key: Dict[str, Any]) -> bool:
        """Deletes an item (player, match, or config) by full key."""
        try:
            self.table.delete_item(Key=key)
            return True
        except Exception as e:
            print(f"Error deleting item: {e}", file=sys.stderr)
            return False

    def query_items_by_pk(self) -> List[Dict[str, Any]]:
        """Fetches all items for the current PK (tournament)."""
        try:
            response = self.table.query(KeyConditionExpression=Key("PK").eq(self.pk))
            return response.get("Items", [])
        except Exception as e:
            print(f"Error querying items by PK: {e}", file=sys.stderr)
            return []




def setup_dynamodb_table(table_name: str):
    """
    Ensures the DynamoDB table exists.
    If not, creates it with the correct PK/SK schema.
    """
    client = boto3.client("dynamodb")
    try:
        client.describe_table(TableName=table_name)
        print(f"DynamoDB table '{table_name}' already exists.", file=sys.stderr)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Creating table '{table_name}'...", file=sys.stderr)
            try:
                client.create_table(
                    TableName=table_name,
                    AttributeDefinitions=[
                        {"AttributeName": "PK", "AttributeType": "S"},
                        {"AttributeName": "SK", "AttributeType": "S"},
                    ],
                    KeySchema=[
                        {"AttributeName": "PK", "KeyType": "HASH"},
                        {"AttributeName": "SK", "KeyType": "RANGE"},
                    ],
                    BillingMode="PAY_PER_REQUEST",  # On-Demand pricing model
                    # ProvisionedThroughput={
                    #     "ReadCapacityUnits": 5,
                    #     "WriteCapacityUnits": 5,
                    # },
                )
                print(f"Waiting for table '{table_name}' to become active...", file=sys.stderr)
                client.get_waiter("table_exists").wait(TableName=table_name)
                print(f"Table '{table_name}' created successfully.", file=sys.stderr)
            except Exception as ce:
                print(f"FATAL: Could not create table. Error: {ce}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"FATAL: Error describing table: {e}", file=sys.stderr)
            raise e
    except Exception as e:
        print(f"FATAL: DynamoDB setup error: {e}", file=sys.stderr)
        sys.exit(1)